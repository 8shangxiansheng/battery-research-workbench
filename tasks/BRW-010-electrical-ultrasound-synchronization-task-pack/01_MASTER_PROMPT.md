# BRW-010 Master Vibe Coding Prompt

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
BRW-007 Adapter / Importer ✅
BRW-008 Time Anchor ✅
BRW-009 Timestamp Engine ✅
```

现在执行：

> **BRW-010 — Electrical–Ultrasound Synchronization**

---

# 0. 第一轮只 Inspect

必须读取：

1. `AGENTS.md`
2. `README.md`
3. development plan / synchronization architecture
4. BRW-003 electrical output contract
5. BRW-004 electrical QA findings
6. BRW-008 anchor semantics
7. BRW-009 output contract / timestamp semantics
8. 当前：
   - `src/battery_workbench/synchronization/`
   - electrical `records.parquet`
   - `timestamped_ultrasound_frames.parquet`
   - timestamp engine manifest
9. 当前 electrical canonical schema
10. 当前 tests

第一轮不修改代码。

---

# 1. 本轮解决的问题

BRW-009 已经得到：

```text
ultrasound frame
→ provisional_absolute_timestamp
```

BRW-010 要回答：

> 对每个 ultrasound frame，
> 哪个 electrical timestamp 距离它最近？

并且：

> 如果最近时间点有多个 electrical row，
> 或者存在等距最近时间点，
> 怎么把不确定性完整保存下来？

---

# 2. Canonical matching direction

固定：

```text
Ultrasound frames = LEFT
Electrical records = RIGHT
```

输出必须保持：

```text
one aligned summary row per ultrasound frame
```

禁止为了 electrical row 数量扩展主 aligned table。

所有候选放独立 candidate table。

---

# 3. Canonical inputs

## Ultrasound

```text
data/processed/synchronization/{battery_id}/{experiment_id}/
timestamped_ultrasound_frames.parquet
```

匹配时间列：

```text
provisional_absolute_timestamp
```

只匹配：

```text
timestamp_available = true
```

## Electrical

```text
data/processed/electrical/{battery_id}/{experiment_id}/records.parquet
```

必须从当前 canonical schema Inspect 出：

```text
electrical absolute timestamp column
stable record locator / record index fields
cycle/step fields available for diagnostics
boundary/start-end marker if available
```

不要猜列名。

---

# 4. Electrical record identity

BRW-010 必须建立稳定的 electrical record locator。

优先级：

```text
1. existing canonical stable record/event/source-row identifier
2. existing raw data sequence identifier
3. only if neither exists:
   stable parquet row ordinal + explicit provenance
```

不要仅凭 timestamp 当 row id。

建议最终候选表至少保存：

```text
electrical_asset_id
electrical_record_locator
electrical_row_index
electrical_source_row_index   # if available
electrical_record_index_raw   # if available
```

实际字段按当前 BRW-003 schema 适配。

禁止为了 BRW-010 修改 Parser 重新造 ID，
除非现有数据确实没有任何可追溯 locator，
且修改经过明确说明。

---

# 5. Matching algorithm

推荐确定性实现：

## Step A

对 electrical records 建立只读 lookup：

```text
timestamp
→ list[electrical records]
```

## Step B

按 unique electrical timestamp 排序。

## Step C

对每个 ultrasound timestamp，
用：

```text
searchsorted
```

或等价算法找到：

```text
previous electrical timestamp
next electrical timestamp
```

## Step D

计算：

```text
abs(ultrasound_ts - electrical_ts)
```

## Step E

取最小 time error。

所有在：

```text
tie_tolerance_s
```

内与最小 error 等价的 timestamp group
都属于 nearest candidates。

---

# 6. Candidate counts

必须区分：

```text
candidate_timestamp_count
candidate_record_count
```

例如：

## Case 1

一个最近 timestamp，
该 timestamp 只有一个 record：

```text
candidate_timestamp_count = 1
candidate_record_count = 1
```

→ UNIQUE

## Case 2

一个最近 timestamp，
但该 timestamp 有 2 个 duplicate records：

```text
candidate_timestamp_count = 1
candidate_record_count = 2
```

→ AMBIGUOUS_DUPLICATE_TIMESTAMP

## Case 3

ultrasound 时间正好在两个 electrical timestamp 中点：

```text
candidate_timestamp_count = 2
candidate_record_count >= 2
```

→ AMBIGUOUS_EQUIDISTANT

---

# 7. No silent ambiguous selection

默认：

```text
candidate_record_count == 1
→ selected electrical record

candidate_record_count != 1
→ selected electrical record = null
```

禁止：

```text
take first
take last
choose lower cycle
choose higher cycle
choose same step
```

这些都没有时间证据。

---

# 8. Match status

至少：

```text
MATCHED_UNIQUE
MATCHED_AMBIGUOUS
OUT_OF_TOLERANCE
TIMESTAMP_UNAVAILABLE
NO_ELECTRICAL_CANDIDATE
```

可以增加：

```text
IDENTITY_ERROR
TIMEZONE_MISMATCH
```

---

# 9. Sync error

定义：

```text
sync_error_s =
minimum absolute temporal distance
between ultrasound timestamp and nearest electrical timestamp group
```

即使 ambiguous：

```text
sync_error_s
```

仍可以有值。

如果：

```text
timestamp unavailable / no electrical data
```

则 null。

---

# 10. Matching tolerance

配置：

```text
configs/synchronization.yaml
```

建议 V1：

```yaml
matching:
  method: nearest
  max_sync_error_s: 1.0
  tie_tolerance_s: 0.000000001
```

重要：

```text
1.0 s
```

是当前 V1 acceptance policy，
不是普适科学定律。

Inspect 时必须先报告：

```text
electrical median positive interval
min interval
max interval
```

如果真实 cadence 与 1 s 明显不符，
先报告，不自行扩大 threshold。

---

# 11. Out-of-tolerance behavior

如果最近候选：

```text
sync_error_s > max_sync_error_s
```

则：

```text
match_status = OUT_OF_TOLERANCE
```

候选仍写入 candidate table，
用于 audit。

但 aligned summary：

```text
selected electrical record = null
```

禁止为了“全匹配”自动放宽 tolerance。

---

# 12. Candidate table

必须生成：

```text
synchronization_candidates.parquet
```

推荐：

```text
one row per ultrasound frame × nearest candidate electrical record
```

至少：

```text
battery_id
experiment_id

ultrasound_asset_id
frame_index_raw
ultrasound_timestamp

electrical_asset_id
electrical_record_locator
electrical_row_index
electrical_timestamp

sync_error_s

candidate_timestamp_rank
candidate_record_rank

within_tolerance

electrical_timestamp_duplicate_count

boundary_flag
boundary_reason
```

不复制 waveform。

---

# 13. Aligned summary table

生成：

```text
aligned_ultrasound_frames.parquet
```

必须保持：

```text
input ultrasound frame count
==
aligned summary row count
```

至少：

```text
battery_id
experiment_id

ultrasound_asset_id
frame_index_raw
waveform_group
waveform_row_index

provisional_absolute_timestamp

match_status

electrical_asset_id
electrical_record_locator
electrical_row_index
electrical_timestamp

sync_error_s
within_tolerance

candidate_timestamp_count
candidate_record_count
sync_ambiguous
ambiguity_type

boundary_flag

anchor_id
anchor_status
validated_sync
```

---

# 14. No waveform duplication

禁止把：

```text
1250 samples
```

塞入 aligned parquet。

只保留：

```text
waveform_group
waveform_row_index
```

---

# 15. Ambiguity type

至少：

```text
NONE
DUPLICATE_ELECTRICAL_TIMESTAMP
EQUIDISTANT_TIMESTAMPS
DUPLICATE_AND_EQUIDISTANT
```

缺少时间时可 null。

---

# 16. Electrical timestamp duplicates

必须独立统计：

```text
duplicate timestamp row count
duplicate timestamp group count
```

与已有 BRW-004 finding 对比。

当前已知：

```text
12 duplicate records
9 duplicate timestamp groups
```

真实执行必须重新从 canonical records 计算。

不要 hard-code。

---

# 17. Boundary diagnostics

需要：

```text
boundary_flag
```

但：

> boundary 只能解释 ambiguity，
> 不能参与 nearest matching。

推荐 boundary evidence：

```text
A. electrical timestamp is duplicated
B. cycle id changes vs adjacent original record
C. step id changes vs adjacent original record
D. explicit start/end marker if canonical schema has it
```

最终：

```text
boundary_flag = any(boundary evidence)
```

并记录：

```text
boundary_reason
```

---

# 18. Boundary calculation must preserve original order

Cycle/Step transition判断必须基于：

```text
electrical canonical event order
```

不能基于 timestamp 排序后的位置。

因为 duplicate timestamp 时排序可能改变 boundary semantics。

匹配可使用 timestamp-sorted lookup copy，
boundary detection 使用 original record order。

---

# 19. No cycle matching

测试必须证明：

如果 synthetic electrical 数据中：

```text
cycle labels 被随机替换
```

但 timestamps 不变，

nearest matching 结果：

```text
electrical record candidate timestamps
sync_error_s
```

保持不变。

这证明 cycle 不是 alignment key。

---

# 20. Non-monotonic electrical timestamps

如果 electrical canonical input 非单调：

- 不修改输入
- 建 timestamp-sorted lookup copy
- 保留 original row locator
- 记录 diagnostic

不要要求用户先重写 records.parquet。

---

# 21. Ultrasound row order

aligned summary 必须保持：

```text
timestamped_ultrasound_frames.parquet
```

原 row order。

不得按 electrical timestamp 重新排序输出。

---

# 22. Multi-ultrasound asset

必须支持：

```text
U001
U002
U003
```

所有 frame 使用各自 BRW-009 timestamp。

BRW-010 不需要重新读取 anchor。

---

# 23. Multi-electrical asset

架构必须允许：

```text
E001
E002
```

如果 records.parquet 已包含：

```text
electrical_asset_id
```

则候选跨所有属于 experiment 的 electrical records 搜索。

如果多个 electrical assets 覆盖重叠时间，
可能产生 ambiguity。

必须保留：

```text
electrical_asset_id
```

不能 filename 猜主文件。

---

# 24. Timezone compatibility

如果 ultrasound timestamp 与 electrical timestamp：

```text
one naive
one aware
```

禁止自动转换。

结果：

```text
TIMEZONE_MISMATCH / FAIL
```

如果两边均 naive：

允许匹配，
但 report：

```text
timezone_known=false
```

---

# 25. Provisional anchor propagation

BRW-009 timestamps 当前来自：

```text
PROVISIONAL anchor
```

因此即使 nearest matching 非常好：

```text
validated_sync
```

默认仍不能自动升级为 true。

BRW-010 V1 推荐：

```text
matching_performed = true
validated_sync = false
sync_semantics = "MATCHED_USING_PROVISIONAL_TIMEBASE"
```

这是匹配成功与独立时钟验证之间的区别。

---

# 26. Quality metrics

Report 至少：

```text
total_ultrasound_frames

matched_unique_count
matched_ambiguous_count
out_of_tolerance_count
timestamp_unavailable_count
no_candidate_count

ambiguous_fraction
within_tolerance_fraction

sync_error_s:
  min
  median
  p95
  max

candidate_record_count distribution

boundary_match_count
ambiguous_boundary_count
```

---

# 27. Sync quality status

建议 experiment level：

```text
PASS
PASS_WITH_WARNINGS
FAIL
```

## PASS

例如：

```text
all timestamp-available frames have unique within-tolerance match
```

## PASS_WITH_WARNINGS

例如：

```text
small number ambiguous boundary matches
some out-of-tolerance frames
provisional anchor
timezone unknown
```

## FAIL

例如：

```text
timestamp columns invalid
identity mismatch
no electrical data
timezone mismatch
cannot persist outputs
```

不要因为：

```text
validated_sync=false
```

单独 FAIL。

---

# 28. Required QA figures

至少 4 张：

## F01 `sync_error_vs_time.png`

x：

```text
ultrasound provisional timestamp / elapsed time
```

y：

```text
sync_error_s
```

## F02 `sync_error_histogram.png`

误差分布。

## F03 `candidate_record_count_vs_time.png`

查看 ambiguity 是否集中在 boundary。

## F04 `match_status_timeline.png`

显示：

```text
unique
ambiguous
out-of-tolerance
unavailable
```

不要画 waveform。

---

# 29. Current real-data expectations

当前：

```text
ultrasound frames = 3999
electrical records = 39996
```

Electrical cadence nominally ~1 s，
Ultrasound frame cadence ~10 s。

因此预期：

```text
绝大多数 frame
→ unique nearest electrical record
```

但：

```text
duplicate electrical timestamp groups
```

可能导致少量 ambiguity。

实际 ambiguous count 必须真实计算，
不要预设 0 或固定数值。

---

# 30. Edge coverage

当前 ultrasound last provisional timestamp
约早于 electrical end：

```text
~2.97 s
```

因此当前数据理论上应处于 electrical coverage 内。

但必须从当前 artifacts 实际验证。

---

# 31. No interpolation

BRW-010 是：

```text
nearest record synchronization
```

不是：

```text
interpolate voltage/current at ultrasound timestamp
```

插值以后如果需要，属于分析层或独立方法。

---

# 32. No selected record for ambiguity

这个是 V1 科研保护规则：

```text
ambiguous
→ selected locator null
```

候选完整保留。

未来 BRW-011 可：

- 保留 ambiguous MeasurementEvent
- 或按研究 policy 排除
- 或引入 boundary resolution policy

但 BRW-010 不擅自解决。

---

# 33. Persistence

推荐：

```text
data/processed/synchronization/{battery_id}/{experiment_id}/
├── time_anchors.json
├── timestamped_ultrasound_frames.parquet
├── timestamp_engine_manifest.json
├── aligned_ultrasound_frames.parquet
├── synchronization_candidates.parquet
└── synchronization_manifest.json
```

---

# 34. Synchronization manifest

至少：

```text
sync_engine_name
sync_engine_version

matching_method
max_sync_error_s
tie_tolerance_s

input paths
input checksums

ultrasound row count
electrical row count

output paths
output checksums

duplicate electrical timestamp stats

match counts
quality metrics

matching_performed
validated_sync
warnings
```

---

# 35. Reports

```text
data/artifacts/{battery_id}/{experiment_id}/synchronization/
├── synchronization_report.json
├── synchronization_report.html
└── figures/
    ├── sync_error_vs_time.png
    ├── sync_error_histogram.png
    ├── candidate_record_count_vs_time.png
    └── match_status_timeline.png
```

---

# 36. Input immutability

不得修改：

```text
records.parquet
cycles.parquet
steps.parquet
timestamped_ultrasound_frames.parquet
time_anchors.json
frames.parquet
waveforms.zarr
```

至少校验：

```text
records.parquet SHA256 before/after
timestamped_ultrasound_frames.parquet SHA256 before/after
```

---

# 37. Tests FIRST

必须先测试。

## T01 exact unique timestamp

→ MATCHED_UNIQUE, error=0。

## T02 nearest previous

正确选择。

## T03 nearest next

正确选择。

## T04 equidistant timestamps

两个 timestamp candidates，
ambiguous，
selected null。

## T05 duplicate electrical timestamp

一个 timestamp group 多条 record，
ambiguous，
selected null。

## T06 duplicate + equidistant

ambiguity type 正确。

## T07 tolerance inclusive boundary

`error == max_sync_error_s`
行为固定并测试。

建议：

```text
within_tolerance = true
```

## T08 out of tolerance

candidate 保留，
selected null。

## T09 empty electrical data

NO_ELECTRICAL_CANDIDATE / FAIL policy明确。

## T10 timestamp unavailable ultrasound frame

不匹配。

## T11 preserve ultrasound row order/count

## T12 electrical non-monotonic

lookup 可排序，
record locator 不变。

## T13 duplicate ultrasound timestamps

各 frame 独立保存，
不 dedupe。

## T14 timezone mismatch

不自动转换。

## T15 naive-naive

允许匹配但 timezone unknown。

## T16 boundary duplicate

boundary_flag true。

## T17 step/cycle transition

boundary flag 可检测，
但不改变 match candidate。

## T18 cycle labels do not affect matching

时间匹配结果不变。

## T19 candidate table completeness

每个 nearest candidate row 都落表。

## T20 ambiguous selected record null

强制。

## T21 sync_error correctness

## T22 multi-ultrasound asset

## T23 multi-electrical asset

保留 asset identity。

## T24 no waveform duplication

## T25 input immutability

## T26 manifest/report contract

## T27 figures

4 张存在且非空。

## T28 real CELL_001 integration

真实运行：

```text
3999 ultrasound rows
39996 electrical rows
```

输出完整 matching statistics。

---

# 38. Real-data Golden review

真实运行后人工 review：

```text
matched unique count
ambiguous count
out-of-tolerance count

sync error:
min
median
p95
max

duplicate electrical:
rows
groups

ambiguous frames:
frame ids
timestamps
candidate records
boundary reasons
```

不要只看总 PASS。

---

# 39. Golden candidate audit

至少独立抽查：

```text
frame 0
frame 1000
frame 2000
frame 3000
frame 3998
```

手工/独立算法确认：

```text
nearest electrical timestamp
sync_error_s
candidate_record_count
```

Golden expected 不能由 production matcher 自己生成。

---

# 40. Public API

推荐：

```python
synchronize_ultrasound_to_electrical(
    *,
    timestamped_frames_path: Path,
    electrical_records_path: Path,
    output_dir: Path,
    config: SynchronizationConfig,
) -> SynchronizationReport
```

建议纯函数：

```python
find_nearest_candidates(
    ultrasound_timestamp,
    electrical_timestamp_index,
    *,
    tie_tolerance_s,
)
```

---

# 41. BRW-011 handoff

BRW-011 应消费：

```text
aligned_ultrasound_frames.parquet
+
synchronization_candidates.parquet
+
electrical records.parquet
+
waveforms.zarr locators
```

生成：

```text
MeasurementEvent
```

BRW-010 不提前构造完整 event。

---

# 42. Forbidden output enrichment

BRW-010 aligned summary 默认不要直接加入：

```text
voltage
current
capacity
temperature
SOC
SOH
```

这些由 BRW-011 根据 selected electrical locator enrichment。

Boundary diagnostics 可以读取 cycle/step，
但不能把 cycle/step 当 matching key。

---

# 43. Scope guard

严格禁止：

- drift correction
- affine clock model
- waveform alignment
- interpolation
- cycle-based synchronization
- step-based synchronization
- SOC-based synchronization
- SOH analysis
- feature extraction
- MeasurementEvent construction
- ML
- Agent
- UI

---

# 44. Quality gates

完成后：

```bash
pytest
ruff check <本次修改文件>
ruff format --check <本次修改文件>
mypy <可运行范围>
git diff --check
```

full-repo mypy 如仍被既有 NumPy/Python stub 环境问题阻断，
记录既有 BRW-TECH issue，
不要误报成 BRW-010 regression。

---

# 45. Final handoff

最终必须报告：

## Status

PASS / PARTIAL / FAIL

## Files changed

## Inputs

Ultrasound rows:
Electrical rows:

## Matching policy

```text
method
max_sync_error_s
tie_tolerance_s
ambiguous-selection policy
```

## Electrical timestamp quality

```text
duplicate rows
duplicate groups
median interval
```

## Matching result

```text
matched unique
matched ambiguous
out of tolerance
timestamp unavailable
no candidates
```

## Sync error

```text
min
median
p95
max
```

## Ambiguity audit

列出真实 ambiguous frame / candidate / boundary 情况。

## Canonical outputs

```text
aligned_ultrasound_frames.parquet
synchronization_candidates.parquet
synchronization_manifest.json
```

## Reports / figures

## Input integrity

## Tests

pytest / coverage / ruff / format / mypy / git diff

## Scientific semantics

明确：

```text
matching_performed=true
validated_sync=false
anchor remains provisional
```

## Scope confirmation

```text
No drift correction
No interpolation
No cycle-based alignment
No MeasurementEvent
```

完成后停止，不进入 BRW-011。
