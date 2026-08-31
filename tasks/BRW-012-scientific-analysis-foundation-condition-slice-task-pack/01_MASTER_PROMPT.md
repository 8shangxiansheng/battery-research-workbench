# BRW-012 Master Vibe Coding Prompt

执行：

> **BRW-012 — Scientific Analysis Foundation / Condition Slice Engine**

已完成：

```text
BRW-003 Electrical Parser ✅
BRW-004 Electrical QA ✅
BRW-005 Ultrasound Parser ✅
BRW-006 Ultrasound QA ✅
BRW-007 Adapter / Importer ✅
BRW-008 Time Anchor ✅
BRW-009 Timestamp Engine ✅
BRW-010 Synchronization ✅
BRW-011 MeasurementEvent ✅
```

## 0. 第一轮只 Inspect

阅读：

1. `AGENTS.md`
2. `README.md`
3. development plan / scientific analysis architecture
4. BRW-011 output contract / event quality policy / BRW-012 handoff
5. 当前：
   - `data/processed/multimodal/CELL_001/EXP_001/measurement_events.parquet`
   - `measurement_event_manifest.json`
   - `measurement_event_candidates.parquet`
6. 当前 `src/battery_workbench/multimodal/`
7. 当前 analysis 目录
8. 当前 tests

第一轮只 Inspect，不改代码。

---

# 1. 本轮唯一目标

建立统一的科研条件切片层：

```text
MeasurementEvent
↓
ConditionSliceSpec
↓
ConditionSliceEngine
↓
AnalysisSlice
```

以后后续科研任务不再自己手写 DataFrame 条件拼接。

---

# 2. Canonical input

只消费：

```text
measurement_events.parquet
```

禁止重新：

```text
读 XLSX
读 TXT
同步
join electrical
构建 MeasurementEvent
```

---

# 3. Default policy

默认：

```text
analysis_eligible_only = true
```

也就是默认排除：

```text
AMBIGUOUS_SYNC
OUT_OF_TOLERANCE
TIMESTAMP_UNAVAILABLE
INTEGRITY_ERROR
```

只有用户显式：

```text
include_ineligible=true
```

才允许包含。

---

# 4. 推荐代码

```text
src/battery_workbench/analysis/
├── __init__.py
├── schemas.py
├── conditions.py
├── slice_id.py
├── slice_engine.py
├── validation.py
├── persistence.py
└── report.py
```

---

# 5. ConditionSliceSpec

至少支持：

## Identity

```text
battery_ids
experiment_ids
ultrasound_asset_ids
```

## Quality

```text
analysis_eligible_only
event_quality_statuses
max_sync_error_s
boundary_flag
```

## Protocol

```text
cycle_indices
step_indices
step_types
```

## Numeric electrical ranges

```text
voltage_v_min/max
current_a_min/max
capacity_ah_min/max
temperature_c_min/max
soc_dod_percent_min/max
```

## Time

```text
elapsed_time_s_min/max
provisional_timestamp_start/end
```

## Null policy

```text
include_null_numeric_values
```

---

# 6. Boolean semantics

同一字段多个值：

```text
OR
```

不同字段：

```text
AND
```

例如：

```text
cycle in [1,2]
AND
step_type in ["..."]
AND
current_a <= 0
```

---

# 7. Range semantics

所有范围：

```text
min inclusive
max inclusive
```

例如：

```text
3.5 <= voltage_v <= 4.0
```

禁止自动交换非法 min/max。

---

# 8. Null semantics

默认：

```text
include_null_numeric_values = false
```

因此 numeric range filter 下：

```text
null → excluded
```

如果显式 true，可以保留 null，但 manifest 必须记录。

---

# 9. SOC/DOD guard

继续使用：

```text
soc_dod_percent
```

禁止重命名：

```text
soc_percent
```

禁止解释成纯 SOC。

---

# 10. Step type

直接使用当前 canonical `step_type` 实际值。

不要擅自把：

```text
恒流放电
```

翻译成另一种内部 primary value。

---

# 11. Sync error filter

允许：

```text
max_sync_error_s
```

这是数据质量筛选。

禁止重新计算 sync error。

---

# 12. Boundary filter

允许：

```text
boundary_flag = true/false
```

默认：

```text
不自动排除 boundary
```

boundary 本身不是坏数据。

---

# 13. 禁止 waveform feature filter

本轮不能出现：

```text
tof_us
fft_peak_hz
waveform_rms_feature
wavelet_energy
```

BRW-012 只筛 MeasurementEvent metadata / electrical state / sync quality。

---

# 14. Deterministic analysis_slice_id

必须由：

```text
input measurement_events checksum
+
normalized ConditionSliceSpec
```

决定。

相同 input + 相同 normalized spec：

```text
same ID
```

不同 input checksum：

```text
different ID
```

禁止 random UUID 作为 canonical slice ID。

---

# 15. Spec normalization

例如：

```text
cycle_indices=[2,1,1]
```

normalized：

```text
[1,2]
```

保存：

```text
requested_spec
normalized_spec
```

list 排序/去重后生成 canonical serialization。

---

# 16. Preserve identities

AnalysisSlice 必须保留：

```text
measurement_event_id
battery_id
experiment_id
ultrasound_asset_id
frame_index_raw
event_order_index
waveform_group
waveform_row_index
```

禁止重新生成 event ID。

---

# 17. Suggested slice columns

至少保留：

```text
measurement_event_id
battery_id
experiment_id
ultrasound_asset_id
frame_index_raw
event_order_index

provisional_absolute_timestamp
elapsed_time_s

waveform_group
waveform_row_index

cycle_index_raw
step_index_raw
step_type

voltage_v
current_a
capacity_ah
charge_capacity_ah
discharge_capacity_ah
energy_wh
power_w
temperature_c
soc_dod_percent

sync_error_s
boundary_flag
event_quality_status
analysis_eligible
```

根据当前真实 schema适配，不伪造不存在的数据。

---

# 18. Output

```text
data/processed/analysis_slices/
{battery_id}/{experiment_id}/{analysis_slice_id}/
├── analysis_slice.parquet
└── analysis_slice_manifest.json
```

report：

```text
data/artifacts/{battery_id}/{experiment_id}/analysis_slices/{analysis_slice_id}/
├── analysis_slice_report.json
└── analysis_slice_report.html
```

---

# 19. Manifest

至少：

```text
slice_engine_name
slice_engine_version
analysis_slice_id

input_path
input_checksum
input_row_count

requested_spec
normalized_spec

output_path
output_checksum
output_row_count
excluded_row_count

filter_breakdown

included_quality_statuses
analysis_eligible_only

warnings
limitations
```

---

# 20. Filter breakdown

至少：

```text
rows_before
rows_after_quality
rows_after_identity
rows_after_cycle
rows_after_step
rows_after_voltage
rows_after_current
rows_after_capacity
rows_after_temperature
rows_after_soc_dod
rows_after_sync_error
rows_after_boundary
rows_after_time
```

空条件阶段可以保持相同数量。

---

# 21. Empty slice

合法条件但 0 rows：

```text
status = EMPTY
```

仍生成：

```text
empty schema-consistent parquet
manifest
report
```

不要 exception。

---

# 22. Invalid filter

例如：

```text
voltage_v_min > voltage_v_max
```

必须 ValidationError。

不能自动 swap。

---

# 23. Unknown step value

例如：

```text
step_types=["FOO"]
```

允许合法执行：

```text
0 rows
+
warning
```

禁止猜 mapping。

---

# 24. Status

```text
READY
READY_WITH_WARNINGS
EMPTY
FAILED
```

---

# 25. Input immutability

不得修改：

```text
measurement_events.parquet
measurement_event_manifest.json
measurement_event_candidates.parquet
```

至少：

```text
measurement_events SHA256 before/after
```

---

# 26. Public API

推荐：

```python
create_analysis_slice(
    *,
    measurement_events_path: Path,
    spec: ConditionSliceSpec,
    output_root: Path,
    config: AnalysisSliceConfig,
) -> AnalysisSliceReport
```

纯 filtering helper：

```python
apply_condition_slice(events, spec)
```

---

# 27. Config

```text
configs/analysis_slice.yaml
```

推荐：

```yaml
analysis_slice:
  version: "0.1.0"

  defaults:
    analysis_eligible_only: true
    include_null_numeric_values: false
    exclude_boundaries: false

  scientific_guards:
    allow_resynchronization: false
    allow_measurement_event_rebuild: false
    allow_waveform_processing: false
    allow_feature_extraction: false
```

---

# 28. Real-data inspect

必须先报告当前真实：

```text
row count
READY
AMBIGUOUS_SYNC
analysis_eligible true/false
```

以及以下列：

```text
cycle_index_raw
step_index_raw
step_type
voltage_v
current_a
capacity_ah
temperature_c
soc_dod_percent
sync_error_s
boundary_flag
waveform_group
waveform_row_index
```

的：

```text
存在性
dtype
null count
min/max or unique values
```

---

# 29. Required real slices

最终至少生成 4 个真实 slice：

## READY_ALL

```text
analysis_eligible_only=true
```

## CYCLE_1

```text
analysis_eligible_only=true
cycle_indices=[1]
```

## DISCHARGE

必须根据当前真实 `step_type` value 定义。

优先：

```text
step_type == actual discharge canonical value
```

不要猜名称。

## MID_SOC_DOD

如果真实 `soc_dod_percent` 有足够 non-null 数据：

```text
40 <= soc_dod_percent <= 60
```

如果字段不可用/基本全 null：

生成：

```text
VOLTAGE_WINDOW
```

作为 fallback，并解释。

---

# 30. Golden audit

每个真实 slice 至少检查：

```text
first
middle
last
```

必须逐行验证满足 spec。

不能只看 row count。

---

# 31. Preserve order

默认保持：

```text
MeasurementEvent order
```

不得按 cycle/step/voltage 自动排序。

---

# 32. No scientific conclusion

BRW-012 禁止输出：

```text
RMS 与 SOC 相关
超声随充电变化
某变量导致 SOH 下降
```

本轮只做数据选择。

---

# 33. No plotting requirement

不强制 plotting。

report 用结构化统计即可。

---

# 34. Tests FIRST

至少：

```text
T01 default eligible only
T02 include ineligible
T03 cycle single
T04 cycle multi OR
T05 step single
T06 step multi OR
T07 cross-field AND
T08 voltage inclusive
T09 current inclusive
T10 capacity
T11 temperature
T12 soc_dod
T13 null excluded
T14 include null
T15 elapsed
T16 timestamp
T17 max sync error
T18 boundary
T19 invalid range
T20 unknown step
T21 deterministic ID
T22 list order normalize
T23 duplicate list normalize
T24 same input/spec same ID
T25 different checksum different ID
T26 preserve event id
T27 preserve waveform locator
T28 no waveform samples
T29 preserve order
T30 empty persistence
T31 filter breakdown
T32 input immutable
T33 real READY_ALL
T34 real CYCLE_1
T35 real DISCHARGE
T36 real MID_SOC_DOD or fallback
```

---

# 35. BRW-013 handoff

BRW-013 将消费：

```text
analysis_slice.parquet
+
waveforms.zarr
```

实现 Ultrasound Feature Engine。

BRW-013 不应该再自己做 event filtering。

---

# 36. Scope guard

严格禁止：

```text
MeasurementEvent rebuild
synchronization
timestamp matching
waveform filtering
feature extraction
TOF
FFT
correlation conclusions
SOH/SOC modeling
ML
Agent
UI
```

---

# 37. Quality gates

完成：

```bash
pytest
ruff check <changed files>
ruff format --check <changed files>
mypy <supported scope>
git diff --check
```

已有 NumPy/Python stub 问题继续记 BRW-TECH。

---

# 38. Final handoff

最终报告：

## Status

PASS / PARTIAL / FAIL

## Files changed

## Input MeasurementEvents

row count
quality composition
analysis eligible

## Supported filters

## Real slices

| Name | Slice ID | Input | Output | Status |
|---|---|---:|---:|---|
| READY_ALL | | | | |
| CYCLE_1 | | | | |
| DISCHARGE | | | | |
| MID_SOC_DOD / fallback | | | | |

## Filter breakdown

## Golden audits

## Canonical outputs

## Input integrity

## Tests

pytest / coverage / ruff / format / mypy / git diff

## Scientific scope confirmation

```text
No feature extraction
No waveform processing
No synchronization
No scientific conclusion
```

完成后停止，不进入 BRW-013。
