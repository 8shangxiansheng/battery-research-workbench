# BRW-008 Master Vibe Coding Prompt

你正在维护：

```text
battery-research-workbench
```

已完成：

```text
BRW-003 Electrical Parser ✅
BRW-004 Electrical QA ✅
BRW-005 Ultrasound Parser ✅
BRW-006 Ultrasound QA ✅
BRW-007 Data Adapter Registry + Experiment Importer ✅
```

现在执行：

> **BRW-008 — Experiment Time Anchor Foundation**

---

# 0. 第一轮先 Inspect

先阅读：

1. `AGENTS.md`
2. `README.md`
3. `docs/development-plan.md`
4. `docs/architecture/system-architecture.md`
5. manifests data contract
6. electrical data contract
7. ultrasound data contract
8. BRW-005 parser manifest/output contract
9. BRW-007 importer/adapter public API
10. domain Battery / Experiment / DataAsset
11. current synchronization package（如果已有 placeholder）
12. current `experiments.csv`
13. current `data_assets.csv`
14. current processed:
   - electrical records/cycles/steps
   - ultrasound frames.parquet
   - ultrasound parser_manifest.json
15. current tests

第一轮只 Inspect，不改代码。

---

# 1. 本轮解决的问题

我们已经知道：

Electrical records 通常有：

```text
absolute timestamps
```

Ultrasound frames 当前有：

```text
elapsed_time_s
```

以及 manifest 可能有：

```text
file_start_time
```

BRW-008 要回答：

> 这个 elapsed-time asset 的“时间零点”依据是什么？
> 这个依据来自哪里？
> 是否存在冲突？
> 如果机械展开成 absolute coverage，它与 experiment/electrical coverage 是否合理？
> 这个 anchor 是 provisional 还是 validated？

---

# 2. 核心公式仅用于 anchor coverage diagnostic

允许：

```text
t_candidate = anchor_datetime + elapsed_time_s
```

用途：

```text
coverage plausibility
```

这一轮禁止把每个 frame 写成正式 synchronized timestamp。

不得产生：

```text
frame_to_electrical_record mapping
```

---

# 3. 推荐代码目录

优先：

```text
src/battery_workbench/synchronization/
├── __init__.py
├── anchors.py
├── schemas.py
├── evidence.py
├── validation.py
├── service.py
└── persistence.py
```

如果当前 synchronization 已有规划结构，
优先遵循现有结构，而不是机械复制目录。

---

# 4. Core models

至少定义：

```text
ExperimentTimeReference
TimeAnchorCandidate
TimeAnchorEvidence
AssetAnchorAssessment
TimeAnchorReport
```

不要 loose dict。

优先 Pydantic / 项目现有 typed schema 风格。

---

# 5. ExperimentTimeReference

至少：

```text
battery_id
experiment_id

experiment_start_time
experiment_end_time

reference_sources

timezone_name
timezone_known
```

当前：

```text
timezone_name = null
timezone_known = false
```

---

# 6. TimeAnchorCandidate

建议字段：

```text
anchor_id

battery_id
experiment_id
asset_id
modality

anchor_datetime
elapsed_time_s_at_anchor

source_type
source_ref

status

timezone_name
timezone_known

notes
```

推荐：

```text
elapsed_time_s_at_anchor = 0.0
```

当 `file_start_time` 表示 elapsed clock 的零点时。

不要把“第一帧时间”误当成“elapsed=0”。

当前第一帧：

```text
elapsed_time_s = 0.031217
```

因此如果 anchor=09:52:31 表示 t=0，则第一帧候选绝对时间应为：

```text
09:52:31.031217
```

---

# 7. Candidate status

至少区分：

```text
UNVERIFIED
PROVISIONAL
CONFLICTING
MANUALLY_ACCEPTED
REJECTED
```

重要：

```text
PROVISIONAL != VERIFIED
```

本轮不需要定义 `VERIFIED_SYNCHRONIZED`。

真正 synchronization verification 属于后续任务。

---

# 8. Anchor source types

至少支持：

```text
MANIFEST_FILE_START
MANUAL_OVERRIDE
```

可记录但默认不自动采用：

```text
FILENAME_HINT
EXPERIMENT_START_HINT
```

如果当前实现没有 filename parser，
不要为 BRW-008 专门写复杂 filename inference。

文件名中的时间字符串只能作为：

```text
raw evidence / hint
```

不能自动升级为 authoritative anchor。

---

# 9. Anchor evidence

TimeAnchorEvidence 至少可以表达：

```text
source_type
source_ref
raw_value
parsed_value
supports_candidate
conflicts_with_candidate
message
```

Evidence != Candidate。

例如：

```text
data_assets.csv file_start_time
```

可以生成 candidate。

而：

```text
filename contains "21.03.01"
```

只能记录 hint，除非有正式格式合同。

---

# 10. Candidate resolution policy

V1 推荐 deterministic priority：

```text
1. explicit MANUAL_OVERRIDE
2. manifest DataAsset.file_start_time
3. no anchor
```

不要自动：

```text
experiment.start_time → ultrasound file_start_time
```

除非 manifest 已明确提供相同值。

Experiment start 可以作为 plausibility evidence，
不是默认替代 anchor。

---

# 11. Manual override

建议支持一个小型 config/input contract：

```text
configs/time_anchor_overrides.yaml
```

或 service 参数。

示例：

```yaml
time_anchors:
  U001:
    anchor_datetime: "2024-01-06T09:52:31"
    elapsed_time_s_at_anchor: 0.0
    reason: "confirmed from instrument metadata"
```

要求：

- manual override 不改 raw manifest
- override provenance 必须保存
- override 优先级高于 manifest
- override 必须可测试

不要做 UI。

---

# 12. Coverage plausibility

对 elapsed-time asset，计算：

```text
candidate_coverage_start
candidate_coverage_end
```

基于：

```text
anchor_datetime
elapsed min
elapsed max
```

并与：

```text
Experiment start/end
Electrical absolute coverage
```

比较。

至少输出：

```text
start_residual_s
end_residual_s
duration_residual_s
overlap_duration_s
coverage_overlap_fraction
```

具体定义必须在代码/docstring 中明确。

---

# 13. Plausibility is not synchronization proof

即使：

```text
coverage overlap ≈ 100%
end residual ≈ few seconds
```

也只能判：

```text
PLAUSIBLE / PROVISIONAL
```

不能：

```text
SYNC_VERIFIED
```

测试必须防止这种语义升级。

---

# 14. Electrical reference window

优先从稳定、已有数据读取：

```text
experiment manifest
+
electrical processed absolute timestamps
```

两者都存在时：

- 都保存 provenance
- 比较是否冲突
- 不静默覆盖

如果 processed electrical 不存在，
experiment manifest 仍可作为 reference window。

BRW-008 不调用 raw XLSX parser 重算。

---

# 15. Ultrasound elapsed coverage

从 BRW-005：

```text
frames.parquet
```

读取：

```text
asset_id
elapsed_time_s min/max
```

并与 parser_manifest 交叉核对。

不重新解析 raw TXT。

---

# 16. Multi-asset requirement

必须支持：

```text
U001
U002
U003
```

每个 ultrasound asset 独立 anchor。

原因：

```text
每个 TXT 的 elapsed time 都可能重新从 0 开始
```

禁止：

```text
把整个 experiment 的所有 ultrasound files 当成一个 elapsed clock
```

除非后续有明确 metadata。

---

# 17. No cycle-based anchor

禁止：

```text
Cycle 1 ↔ U001
Cycle 2 ↔ U002
```

作为默认逻辑。

Cycle 不是跨文件时间对齐主键。

---

# 18. Duplicate electrical timestamps

已知 electrical record 在 step/cycle boundary 有重复 timestamp。

BRW-008 只处理 coverage/reference window，
因此不得假设：

```text
timestamp → unique electrical row
```

真正 ambiguity handling 留给 BRW-010。

可以在 report limitations 中记录：

```text
electrical duplicate timestamps exist
```

但本轮不解决。

---

# 19. Timezone guard

如果 input datetime 没 timezone：

```text
timezone_known = false
timezone_name = null
```

绝不能：

```text
attach UTC
convert timezone
```

JSON 输出保持无 offset ISO datetime。

---

# 20. Missing anchor behavior

如果某 asset：

```text
file_start_time = null
```

且没有 manual override：

```text
anchor_status = UNVERIFIED
selected_anchor = null
```

report：

```text
PASS_WITH_WARNINGS
```

只要结构本身可处理。

不要发明：

```text
experiment_start_time
filename time
```

作为替代。

---

# 21. Conflict handling

例如：

```text
manual override = 10:00:00
manifest anchor = 09:52:31
```

需要记录两条 evidence/candidate。

如果 manual override 被选中：

```text
selected source = MANUAL_OVERRIDE
```

同时：

```text
conflict flag = true
```

不能静默丢掉 manifest 候选。

---

# 22. Configurable plausibility thresholds

建议：

```text
configs/time_anchor.yaml
```

例如：

```yaml
time_anchor:
  version: "0.1.0"

  plausibility:
    max_start_residual_s: 60.0
    max_end_residual_s: 60.0
    min_overlap_fraction: 0.95
```

这些只是：

```text
diagnostic policy
```

不是科学同步定律。

不要用 threshold 自动产生 VERIFIED。

---

# 23. Canonical persisted output

建议：

```text
data/processed/synchronization/{battery_id}/{experiment_id}/
└── time_anchors.json
```

这是 BRW-009 的 machine input。

至少包含：

```text
experiment_reference
asset anchor assessments
selected candidate
candidate provenance
coverage diagnostics
limitations
```

---

# 24. QA/report artifact

另外生成：

```text
data/artifacts/{battery_id}/{experiment_id}/time_anchor/
├── time_anchor_report.json
└── time_anchor_report.html
```

可选：

```text
time_anchor_candidates.csv
```

但 canonical machine state 仍以：

```text
time_anchors.json
```

为准。

---

# 25. TimeAnchorReport status

建议：

```text
PASS
PASS_WITH_WARNINGS
FAIL
```

## PASS

所有需要 elapsed anchor 的 asset 都有非冲突 provisional/manual anchor，
coverage diagnostics 可计算。

## PASS_WITH_WARNINGS

例如：

```text
missing anchor
candidate conflict
coverage mismatch
timezone unknown
```

注意 timezone unknown 可以是 limitation，
不必单独让整个任务 FAIL。

## FAIL

例如：

```text
manifest/data structure invalid
selected anchor cannot parse
asset identity inconsistent
processed ultrasound metadata unreadable
```

---

# 26. Current real-data baseline

当前预期：

```text
battery_id = CELL_001
experiment_id = EXP_001

E001 = electrical
U001 = ultrasound
```

Electrical experiment/reference:

```text
start = 2024-01-06 09:52:31
end   = 2024-01-06 20:58:54
```

U001:

```text
manifest file_start_time =
2024-01-06 09:52:31

elapsed_min =
0.031217

elapsed_max =
39980.03
```

如果 manifest anchor 解释为：

```text
elapsed=0
```

则机械 coverage 应约为：

```text
first frame:
2024-01-06 09:52:31.031217

last frame:
2024-01-06 20:58:51.03
```

最后一帧距离 experiment/electrical end 约：

```text
-2.97 s
```

Agent 必须从真实数据重新计算，
不要只复制这些 expected。

---

# 27. Current real-data expected semantic result

推荐：

```text
selected anchor:
MANIFEST_FILE_START

status:
PROVISIONAL

coverage:
PLAUSIBLE

validated_sync:
false
```

这三个语义不能混淆。

---

# 28. Filename hint

当前文件名：

```text
export - 2024.01.06 - 21.03.01.txt
```

可以在 report 中原样记录。

禁止断言：

```text
21:03:01 = acquisition start
21:03:01 = acquisition end
```

其含义当前 UNKNOWN。

---

# 29. Required public service

推荐：

```python
assess_experiment_time_anchors(
    experiment_id: str,
    *,
    processed_root: Path,
    manifest_root: Path,
    config: TimeAnchorConfig,
    overrides: TimeAnchorOverrides | None = None,
) -> TimeAnchorReport
```

以及 persistence：

```python
write_time_anchor_state(...)
```

如现有 service conventions 不同，
可合理适配。

---

# 30. Tests FIRST

必须先测试。

## T01 Anchor schema

naive datetime 保持 naive。

## T02 Manifest file_start_time

生成：

```text
MANIFEST_FILE_START
PROVISIONAL
```

## T03 Mechanical coverage

已知 anchor + elapsed min/max，
coverage 数值正确。

## T04 First elapsed not zero

验证：

```text
anchor 不是 first frame timestamp
```

## T05 Missing anchor

selected anchor null，
warning，不猜值。

## T06 Manual override priority

manual > manifest，
同时保留 manifest evidence。

## T07 Candidate conflict

冲突显式记录。

## T08 Plausible coverage

可以标 plausible，
但 `validated_sync=false`。

## T09 Bad coverage

warning/conflict，
但不自动修正 anchor。

## T10 Timezone unknown

不加 UTC/Z。

## T11 Filename hint guard

文件名包含时间，
但不会自动变 authoritative candidate。

## T12 Multi ultrasound assets

每个 asset 独立 anchor。

## T13 Elapsed reset

U001/U002 都可从 0 开始，
不会拼接成一个 clock。

## T14 No cycle dependency

Anchor engine 不需要 cycle mapping。

## T15 Electrical duplicate timestamp guard

BRW-008 不尝试唯一 record lookup。

## T16 Parser outputs read-only

不修改：

```text
electrical parquet
frames.parquet
parser_manifest
```

## T17 Canonical JSON contract

`time_anchors.json` schema validate。

## T18 Report contract

JSON / HTML。

## T19 Current CELL_001 integration

验证真实：

```text
U001 selected candidate source = MANIFEST_FILE_START
status = PROVISIONAL
validated_sync = false
```

并核对 mechanical coverage。

---

# 31. Input immutability

BRW-008 只读：

```text
manifests
electrical processed outputs
ultrasound processed outputs
```

至少对关键 input 做 before/after checksum 或 content checksum。

不得修改：

```text
data_assets.csv
experiments.csv
frames.parquet
waveforms.zarr
records.parquet
parser manifests
```

---

# 32. What BRW-009 will consume

BRW-008 完成后，BRW-009 应只需要读取：

```text
time_anchors.json
+
frames.parquet
```

然后才能生成：

```text
per-frame provisional absolute timestamp
```

BRW-009 仍不负责最终 record matching。

---

# 33. Scope guard

本轮禁止：

- electrical row matching
- nearest-neighbor sync
- interpolation onto electrical time
- drift estimation
- affine clock fit
- cycle mapping
- step mapping
- SOC mapping
- cross-correlation alignment
- TOF
- FFT
- MeasurementEvent
- ML
- Agent
- UI

---

# 34. Quality gates

完成后：

```bash
pytest
ruff check <本次修改文件>
ruff format --check <本次修改文件>
mypy <本次修改文件或 src，按当前环境能力>
git diff --check
```

如果 full-repo mypy 仍被已知 NumPy/Python 环境问题阻断，
明确记录为既有 BRW-TECH issue，
不要误报成 BRW-008 error。

---

# 35. Final handoff

最终必须报告：

## Status
PASS / PARTIAL / FAIL

## Files changed

## Experiment reference window

## Asset anchors

表：

```text
asset
source
anchor_datetime
status
coverage plausibility
validated_sync
```

## Evidence

## Conflicts

## Current CELL_001 result

至少：

```text
U001
MANIFEST_FILE_START
PROVISIONAL
validated_sync=false
```

## Coverage diagnostics

## Timezone limitation

## Canonical artifact

```text
time_anchors.json
```

## Reports

## Input integrity

## Tests

pytest / coverage / ruff / format / mypy / git diff

## Scope confirmation

明确：

```text
No frame↔electrical matching
No drift correction
No cycle mapping
```

完成后停止，不进入 BRW-009。
