# BRW-009 Master Vibe Coding Prompt

你正在维护：

```text
battery-research-workbench
```

当前已完成：

```text
BRW-003 Electrical Parser ✅
BRW-004 Electrical QA ✅
BRW-005 Ultrasound Parser ✅
BRW-006 Ultrasound QA ✅
BRW-007 Data Adapter Registry / Experiment Importer ✅
BRW-008 Experiment Time Anchor Foundation ✅
```

现在执行：

> **BRW-009 — Timestamp Construction Engine**

---

# 0. 第一轮先 Inspect

必须阅读：

1. `AGENTS.md`
2. `README.md`
3. `docs/development-plan.md`
4. synchronization architecture/docs
5. BRW-005 output contract
6. BRW-008:
   - master prompt
   - output contract
   - data model
   - anchor semantics
7. 当前：
   - `src/battery_workbench/synchronization/`
   - `frames.parquet`
   - `parser_manifest.json`
   - `time_anchors.json`
8. 当前 tests
9. 当前 CELL_001 / EXP_001 artifacts

第一轮只 Inspect，不改代码。

---

# 1. 本轮解决的问题

BRW-008 已回答：

> “这个 elapsed clock 的 anchor 是什么？”

BRW-009 回答：

> “给定 anchor 和 elapsed_time_s，每个 frame 的 provisional absolute timestamp 是什么？”

---

# 2. Canonical formula

V1 固定：

```text
t_abs =
anchor_datetime
+
(elapsed_time_s - elapsed_time_s_at_anchor)
```

要求：

- datetime arithmetic deterministic
- 保留微秒精度
- 不使用 float timestamp epoch roundtrip造成不必要精度损失
- 不做 drift correction
- clock scale 固定为 1.0

---

# 3. V1 Clock Model

定义：

```text
OFFSET_ONLY
```

推荐 schema：

```text
ClockModel
```

至少：

```text
model_type = "OFFSET_ONLY"
anchor_id
anchor_datetime
elapsed_time_s_at_anchor
scale = 1.0
offset_s = 0.0
drift_enabled = false
```

注意：

`offset_s` 如没有额外人工校准，应为 0.0。

不要在 BRW-009 自动拟合：

```text
a
b
drift ppm
```

---

# 4. Future-proof but no overengineering

可以让 schema 为未来保留：

```text
AFFINE
```

扩展空间，但本轮不能启用。

当前唯一允许执行：

```text
OFFSET_ONLY
```

测试必须保证：

```text
drift_enabled = false
scale = 1.0
```

---

# 5. Recommended code structure

如果 BRW-008 已建立：

```text
src/battery_workbench/synchronization/
```

优先扩展：

```text
clock.py
timestamp_engine.py
timestamp_validation.py
timestamp_persistence.py
```

或遵循现有模块命名。

不要重写 BRW-008 anchor service。

---

# 6. Inputs

BRW-009 canonical inputs：

## A. BRW-008

```text
data/processed/synchronization/{battery_id}/{experiment_id}/time_anchors.json
```

这是 anchor source of truth。

## B. BRW-005

```text
data/processed/ultrasound/{battery_id}/{experiment_id}/frames.parquet
```

提供：

```text
asset identity
frame identity
elapsed_time_s
```

---

# 7. Important: existing `absolute_timestamp` in frames.parquet

BRW-005 可能已经机械生成过：

```text
absolute_timestamp
```

BRW-009 **不得把这个字段当 canonical source of truth**。

原因：

```text
BRW-005 absolute_timestamp
```

是在 parser 层根据 manifest `file_start_time` 机械计算的。

而现在正式时间语义应该经过：

```text
BRW-008 anchor assessment
→ BRW-009 timestamp engine
```

因此：

```text
time_anchors.json
```

优先级高于 parser 的 legacy/provisional `absolute_timestamp`。

---

# 8. Existing parser timestamp diagnostic

如果 frames.parquet 已有：

```text
absolute_timestamp
```

BRW-009 应：

```text
recompute canonical provisional timestamp
↓
compare legacy parser absolute_timestamp
```

至少输出：

```text
legacy_timestamp_available
legacy_timestamp_delta_s
legacy_timestamp_match
```

但：

```text
legacy parser timestamp
```

不能决定 BRW-009 timestamp。

---

# 9. Missing selected anchor

如果某 asset：

```text
selected_anchor = null
```

则：

```text
timestamp_available = false
provisional_absolute_timestamp = null
```

并记录：

```text
MISSING_SELECTED_ANCHOR
```

默认不 FAIL 整个 experiment，只要 engine 能结构化处理。

推荐 overall：

```text
PASS_WITH_WARNINGS
```

---

# 10. Rejected / conflicting anchor

如果 BRW-008 asset：

```text
anchor_status = REJECTED
```

或无可用 selected candidate：

禁止 timestamp construction。

如果：

```text
anchor_status = CONFLICTING
```

但 BRW-008 已明确 selected candidate：

可以按 selected candidate 计算，但必须传播：

```text
anchor_conflict = true
timestamp_status = PROVISIONAL_WITH_WARNING
```

不要重新在 BRW-009 做 candidate selection。

---

# 11. Anchor status propagation

每一帧至少保留：

```text
anchor_id
anchor_source_type
anchor_status
```

不能只存 timestamp 数字而丢 provenance。

---

# 12. Canonical per-frame output

建议：

```text
data/processed/synchronization/{battery_id}/{experiment_id}/
├── time_anchors.json
├── timestamped_ultrasound_frames.parquet
└── timestamp_engine_manifest.json
```

---

# 13. `timestamped_ultrasound_frames.parquet` schema

至少：

```text
battery_id
experiment_id

ultrasound_asset_id
source_file
source_line_index
frame_index_raw
waveform_group
waveform_row_index

elapsed_time_s

anchor_id
anchor_source_type
anchor_status
anchor_datetime
elapsed_time_s_at_anchor

clock_model_type
clock_scale
clock_offset_s
drift_enabled

provisional_absolute_timestamp
timestamp_available

timezone_known
timezone_name

legacy_parser_timestamp
legacy_timestamp_delta_s
legacy_timestamp_match
```

不要把 waveform 本体复制进 Parquet。

---

# 14. Preserve frame identity exactly

必须保证：

```text
input frame count == output row count
```

默认不得：

```text
drop
sort
deduplicate
reindex frame_index_raw
```

输出行序：

优先保持原 frames.parquet 行序。

如果需要 per-asset calculation，
计算结束后必须恢复稳定原顺序。

---

# 15. No silent sorting

如果某 asset：

```text
elapsed_time_s non-monotonic
```

BRW-009：

- 记录 diagnostic
- 仍按每行自己的 elapsed 值计算 timestamp
- 不自动排序输入
- 不修正 elapsed

是否标 warning 由 validation policy 决定。

---

# 16. Duplicate elapsed timestamps

如果同一 asset 出现：

```text
duplicate elapsed_time_s
```

允许生成相同 provisional timestamp。

不得自动：

```text
+ epsilon
deduplicate
```

只记录：

```text
duplicate_elapsed_count
duplicate_timestamp_count
```

---

# 17. Multi-asset handling

必须支持：

```text
U001
U002
U003
```

每个 asset：

```text
读取自己的 selected anchor
读取自己的 elapsed clock
独立 timestamp construction
```

禁止：

```text
U002 elapsed 接在 U001 后面
```

因为不同 TXT 可能 elapsed reset。

---

# 18. Asset identity match

time_anchors.json 和 frames.parquet 必须严格核对：

```text
battery_id
experiment_id
asset_id
```

如果 frames 中 asset 没有 anchor assessment：

```text
warning / timestamp unavailable
```

如果 anchor state 中存在 frames 不存在的 asset：

```text
orphan anchor diagnostic
```

不能静默忽略 identity mismatch。

---

# 19. Timestamp precision

要求：

- 至少 microsecond precision
- JSON / Parquet round-trip 后值稳定
- 不用字符串拼接计算
- 不把 elapsed 四舍五入到秒

当前：

```text
0.031217 s
```

必须保留下来。

---

# 20. Timezone guard

如果 BRW-008：

```text
timezone_known = false
```

则 BRW-009：

```text
provisional_absolute_timestamp
```

保持 naive datetime。

禁止：

```text
append Z
localize UTC
convert timezone
```

---

# 21. Coverage validation

BRW-009 需要重新从 per-frame timestamps 得到：

```text
timestamp_min
timestamp_max
duration
```

然后与 BRW-008 assessment 中的 coverage diagnostic 对比。

目的是：

> 验证 timestamp construction 与 anchor assessment 一致。

不是做 Electrical matching。

至少：

```text
derived_start_matches_anchor_assessment
derived_end_matches_anchor_assessment
```

---

# 22. No electrical access in core engine

Timestamp Engine 核心 API 不应该需要：

```text
records.parquet
cycles.parquet
steps.parquet
```

BRW-009 核心输入只应是：

```text
time_anchors.json
frames.parquet
```

如果 integration report 想引用 experiment reference，
可以读取 BRW-008 state，
但不能 query electrical rows。

---

# 23. Public API

推荐：

```python
build_ultrasound_timestamps(
    *,
    frames_path: Path,
    time_anchor_state_path: Path,
    output_dir: Path,
    config: TimestampEngineConfig,
) -> TimestampEngineReport
```

或项目现有 service convention。

建议另有纯函数：

```python
construct_timestamp(
    anchor_datetime: datetime,
    elapsed_time_s: float,
    elapsed_time_s_at_anchor: float,
) -> datetime
```

方便独立测试。

---

# 24. TimestampEngineReport

至少：

```text
battery_id
experiment_id
engine_version

input_frame_count
output_frame_count

assets

timestamp_available_count
timestamp_missing_count

clock_models

warnings
errors

status

validated_sync = false
```

注意：

```text
validated_sync
```

仍然必须是：

```text
false
```

---

# 25. Per-asset diagnostics

至少：

```text
asset_id

frame_count
timestamp_available_count

elapsed_min_s
elapsed_max_s

timestamp_min
timestamp_max

is_elapsed_strictly_increasing
is_timestamp_strictly_increasing

duplicate_elapsed_count
duplicate_timestamp_count

anchor_id
anchor_status

legacy_timestamp_compare_count
legacy_timestamp_max_abs_delta_s
```

---

# 26. Legacy timestamp tolerance

配置：

```text
legacy_timestamp_tolerance_s
```

例如：

```text
1e-6
```

仅用于：

```text
BRW-005 legacy parser timestamp
vs
BRW-009 timestamp
```

的一致性诊断。

不能用于 Electrical sync。

---

# 27. Current CELL_001 expected values

从真实数据重新计算。

当前预期：

```text
U001 frames = 3999
anchor = 2024-01-06 09:52:31
elapsed_at_anchor = 0.0

first elapsed = 0.031217
last elapsed = 39980.03
```

因此预计：

```text
first provisional timestamp
=
2024-01-06 09:52:31.031217

last provisional timestamp
=
2024-01-06 20:58:51.030000
```

必须从实际 repository data 验证，
不要硬编码到 production code。

---

# 28. Current parser legacy comparison

因为 BRW-005 当前也基于：

```text
file_start_time + elapsed
```

如果 BRW-008 selected anchor 没有改变，

预计：

```text
legacy timestamp delta ≈ 0
```

这是 regression evidence。

但它不代表 synchronization 已验证。

---

# 29. Timestamp Engine Manifest

生成：

```text
timestamp_engine_manifest.json
```

至少：

```text
engine_name
engine_version

input paths
input checksums

time_anchor_state checksum

output path
output checksum

clock_model_type
drift_enabled

asset row counts

warnings
```

---

# 30. Report artifacts

建议：

```text
data/artifacts/{battery_id}/{experiment_id}/timestamp_engine/
├── timestamp_engine_report.json
└── timestamp_engine_report.html
```

可选 QA figure：

```text
timestamp_vs_frame_index.png
```

但本轮不是 plotting task，不强制。

---

# 31. Input immutability

不得修改：

```text
time_anchors.json
frames.parquet
waveforms.zarr
parser_manifest.json
electrical processed outputs
```

至少校验：

```text
frames.parquet checksum before/after
time_anchors.json checksum before/after
```

---

# 32. Tests FIRST

必须先写测试。

## T01 Basic timestamp arithmetic

```text
T0 + elapsed
```

正确到 microseconds。

## T02 Non-zero elapsed_at_anchor

例如：

```text
anchor_datetime = 12:00:10
elapsed_at_anchor = 10
frame elapsed = 15
→ 12:00:15
```

## T03 First elapsed is not zero

验证第一帧 timestamp 不等于 anchor 本身。

## T04 Missing anchor

timestamp null + warning。

## T05 Rejected anchor

不得计算 timestamp。

## T06 Conflicting but selected candidate

允许 provisional timestamp，
传播 conflict warning。

## T07 Timezone unknown

保持 naive。

## T08 Timezone known synthetic

如果输入是 aware datetime，
保持 timezone information，
不擅自转换。

## T09 Multi asset

不同 asset 使用不同 anchor。

## T10 Elapsed reset

U001/U002 都从接近 0 开始，
各自独立。

## T11 Preserve row count/order

输入输出完全一致。

## T12 Duplicate elapsed

不修改、不加 epsilon。

## T13 Non-monotonic elapsed

不排序、不修正。

## T14 Identity mismatch

frames asset 无 anchor assessment → explicit diagnostic。

## T15 Orphan anchor

anchor state 有 asset 但 frames 无对应行 → diagnostic。

## T16 Legacy timestamp exact match

delta≈0。

## T17 Legacy timestamp mismatch

只 warning，不改 canonical timestamp。

## T18 Parquet round-trip

timestamp precision 保留。

## T19 Manifest checksum / input immutability

## T20 No electrical dependency

核心 engine 测试不需要 records.parquet。

## T21 No drift

clock_scale=1 / drift=false。

## T22 Canonical report schema

## T23 Real CELL_001 integration

至少验证：

```text
3999 rows
first timestamp
last timestamp
validated_sync=false
```

---

# 33. Real-data Golden check

建议独立核对：

```text
frame 0
frame 1000
frame 2000
frame 3000
frame 3998
```

对每个：

```text
expected =
anchor + elapsed
```

Golden expected 不能由 production timestamp engine 自己生成。

用独立 Python datetime arithmetic / fixture calculation。

---

# 34. Status rules

## PASS

所有有 selected anchor 的 frames 都成功 timestamp，
没有结构问题。

## PASS_WITH_WARNINGS

例如：

```text
some assets missing anchor
legacy parser timestamp mismatch
non-monotonic elapsed
duplicate elapsed
anchor conflict propagated
```

## FAIL

例如：

```text
time_anchors.json invalid
frames schema invalid
battery/experiment identity mismatch
cannot persist output
```

---

# 35. Scientific guard

必须显式输出：

```text
validated_sync = false
electrical_matching_performed = false
drift_correction_applied = false
cycle_mapping_performed = false
```

---

# 36. Duplicate Electrical timestamp reminder

当前 Electrical 存在 boundary duplicate timestamps。

BRW-009：

```text
不读取、不解决
```

BRW-010 才负责：

```text
candidate_record_count
sync_ambiguous
boundary_flag
```

---

# 37. Scope guard

严格禁止：

- nearest electrical timestamp
- merge_asof with electrical
- record lookup
- sync_error_s to electrical
- ambiguity resolution
- cycle/step/SOC enrichment
- drift estimation
- clock affine fitting
- waveform cross-correlation alignment
- MeasurementEvent
- ML
- Agent
- UI

---

# 38. Quality gates

完成后：

```bash
pytest
ruff check <本次修改文件>
ruff format --check <本次修改文件>
mypy <本次修改文件或可运行范围>
git diff --check
```

如果 full repo mypy 仍被既有 NumPy/Python stub 环境问题阻断，
记录为既有 BRW-TECH，不把它算成 BRW-009 regression。

---

# 39. Final handoff

必须报告：

## Status
PASS / PARTIAL / FAIL

## Files changed

## Clock model

必须明确：

```text
OFFSET_ONLY
scale=1.0
drift=false
```

## Input state

frames:
time_anchors:

## Per-asset timestamps

表：

```text
asset
frames
anchor
first timestamp
last timestamp
timestamp available
```

## Legacy parser timestamp comparison

## Multi-asset behavior

## Provenance

## Canonical outputs

```text
timestamped_ultrasound_frames.parquet
timestamp_engine_manifest.json
```

## Input integrity

## Tests

pytest / coverage / ruff / format / mypy / git diff

## Scope confirmation

明确：

```text
No electrical row matching
No sync_error_s
No drift correction
No cycle mapping
validated_sync=false
```

完成后停止，不进入 BRW-010。
