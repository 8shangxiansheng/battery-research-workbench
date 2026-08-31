# BRW-011 Master Vibe Coding Prompt

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
BRW-010 Electrical–Ultrasound Synchronization ✅
```

现在执行：

> **BRW-011 — MeasurementEvent Canonical Multimodal Layer**

# 0. 第一轮只 Inspect

必须读取：

1. `AGENTS.md`
2. `README.md`
3. development plan / architecture docs
4. BRW-003 output contract
5. BRW-005 output contract
6. BRW-010 output contract / matching semantics / boundary policy / BRW-011 handoff contract
7. 当前：
   - `aligned_ultrasound_frames.parquet`
   - `synchronization_candidates.parquet`
   - `records.parquet`
   - `frames.parquet`
   - `waveforms.zarr` locator schema
8. 当前 electrical canonical columns
9. 当前 synchronization schemas
10. 当前 tests

第一轮只 Inspect，不修改代码。

# 1. 本轮解决的问题

BRW-010 已回答：

> ultrasound frame 对应哪些 nearest electrical record candidate？

BRW-011 要回答：

> 如何把已经对齐的 ultrasound + electrical state 组织成一个稳定、可查询、可用于后续科研分析的数据模型？

# 2. Canonical event grain

固定：

```text
1 MeasurementEvent = 1 ultrasound frame
```

因此：

```text
MeasurementEvent row count == aligned_ultrasound_frames row count
```

禁止因为 ambiguous candidates 展开主 event table。

候选证据放独立 candidate relation table。

# 3. Canonical event identity

定义 deterministic：

```text
measurement_event_id
```

推荐由：

```text
battery_id + experiment_id + ultrasound_asset_id + frame_index_raw
```

生成。

要求：

- deterministic
- repeat run 一致
- 不依赖 DataFrame row number
- 不依赖 electrical timestamp
- 不依赖 selected electrical record

ambiguous event 也必须有稳定 ID。

# 4. Inputs

A. `aligned_ultrasound_frames.parquet`：frame identity / timestamp / match status / selected electrical locator / sync error / ambiguity / boundary / anchor provenance。

B. `synchronization_candidates.parquet`：ambiguous candidate evidence。

C. `records.parquet`：只用于 selected unique electrical locator → exact electrical state enrichment。

D. waveform locator：只保留 `waveform_group` / `waveform_row_index`，不复制 waveform samples。

# 5. MeasurementEvent schema

至少包含：

## Identity

```text
measurement_event_id
battery_id
experiment_id
```

## Ultrasound

```text
ultrasound_asset_id
frame_index_raw
event_order_index
source_file
source_line_index
waveform_group
waveform_row_index
```

## Time

```text
provisional_absolute_timestamp
elapsed_time_s
timezone_known
timezone_name
```

## Synchronization

```text
match_status
sync_error_s
within_tolerance
candidate_timestamp_count
candidate_record_count
sync_ambiguous
ambiguity_type
boundary_flag
matching_performed
validated_sync
sync_semantics
anchor_id
anchor_status
```

## Selected electrical identity

仅 unique match：

```text
electrical_asset_id
electrical_record_locator
electrical_row_index
electrical_timestamp
```

ambiguous / OOT / unavailable：这些字段必须 null。

## Electrical state

unique selected record 时才 enrichment。实际字段按当前 canonical schema Inspect 后适配，候选 whitelist：

```text
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
contact_resistance_mohm
dq_dv_raw
```

不要猜不存在字段。

# 6. Electrical field semantics

必须复用 BRW-003 canonical meaning。

特别：

```text
soc_dod_percent
```

仍然只是 raw `SOC/DOD(%)` canonical field，禁止改成 `soc_percent`。

`dq_dv_raw` 必须保持 raw / unsmoothed / unfiltered。

BRW-011 不做 dQ/dV smoothing / peak detection。

# 7. Temperature

若 records 已有 canonical temperature，直接用。

若只在 aux parquet 中，允许按 BRW-003 既有 stable identity / row mapping deterministic join；禁止重新按 timestamp nearest matching 温度。

# 8. Enrichment rule

固定：

```text
MATCHED_UNIQUE + selected locator exists
→ exact electrical enrichment
```

否则 electrical state fields = null。

禁止 ambiguous → candidate 0。

# 9. Other event statuses

OUT_OF_TOLERANCE：event 保留，electrical state null。

TIMESTAMP_UNAVAILABLE：event 保留，timestamp 可 null，electrical fields null。

# 10. Candidate relation

生成：

```text
measurement_event_candidates.parquet
```

它只是给 BRW-010 candidate evidence 加上 `measurement_event_id`。

禁止重新计算 candidate、减少 candidate 或按 cycle/step 决策。

# 11. Canonical outputs

```text
data/processed/multimodal/{battery_id}/{experiment_id}/
├── measurement_events.parquet
├── measurement_event_candidates.parquet
└── measurement_event_manifest.json
```

# 12. One event per frame invariant

必须：

```text
aligned rows == event rows
measurement_event_id unique
```

输出保持 ultrasound event order，不按 cycle/step/electrical row 排序。

# 13. Exact selected electrical locator validation

如果 selected locator 在 records 找不到：FAIL / INTEGRITY_ERROR。

如果 selected locator 在 records 命中多行：FAIL。

selected locator 必须唯一定位一条 electrical row。

# 14. No timestamp-based rejoin

严格禁止：

```text
merge_asof
nearest timestamp
timestamp equality lookup
```

只允许：

```text
BRW-010 selected electrical locator → exact identity join
```

# 15. Boundary / sync metadata propagation

`boundary_flag`、`boundary_reason`、`sync_error_s`、`match_status`、`validated_sync` 只传播，不重新计算。

当前 `validated_sync=false` 必须保持 false。

# 16. Event quality status

建议：

```text
READY
AMBIGUOUS_SYNC
OUT_OF_TOLERANCE
TIMESTAMP_UNAVAILABLE
INTEGRITY_ERROR
```

映射：

```text
MATCHED_UNIQUE + locator valid + within tolerance → READY
MATCHED_AMBIGUOUS → AMBIGUOUS_SYNC
OUT_OF_TOLERANCE → OUT_OF_TOLERANCE
TIMESTAMP_UNAVAILABLE → TIMESTAMP_UNAVAILABLE
```

不要把 READY 称为 scientifically validated。

# 17. analysis_eligible

V1：

```text
READY → true
其他 → false
```

这是 workflow policy，不是 ground-truth certification。

# 18. Candidate count invariant

对 ambiguous event：

```text
measurement_event_candidates rows for event
== candidate_record_count
```

必须测试。

# 19. Electrical whitelist

禁止 records 全列无脑复制。

使用明确 whitelist；缺失字段记录 limitation。

# 20. Multi-asset / multi-battery

必须保留 asset identity，核心 service 以 battery_id / experiment_id scope。

不 hard-code CELL_001 / EXP_001。

# 21. Public API

推荐：

```python
build_measurement_events(
    *,
    aligned_frames_path: Path,
    sync_candidates_path: Path,
    electrical_records_path: Path,
    output_dir: Path,
    config: MeasurementEventConfig,
) -> MeasurementEventReport
```

# 22. Manifest

生成 `measurement_event_manifest.json`，至少：

```text
builder_name
builder_version
input paths/checksums
input aligned row count
input candidate row count
electrical row count
output paths/checksums
event row count
candidate relation row count
event quality counts
electrical enrichment fields
matching_recomputed=false
validated_sync
warnings
```

# 23. Report

```text
data/artifacts/{battery_id}/{experiment_id}/measurement_events/
├── measurement_event_report.json
└── measurement_event_report.html
```

至少报告：

```text
event count
READY / AMBIGUOUS_SYNC / OOT / UNAVAILABLE
analysis eligible count/fraction
electrical enrichment coverage
candidate relation consistency
waveform locator validity
```

# 24. Waveform locator validation

每 event 的 waveform locator 必须可追溯；可验证 Zarr group/row range，但禁止读取全部 waveform 做计算。

# 25. Input immutability

不得修改：

```text
aligned_ultrasound_frames.parquet
synchronization_candidates.parquet
records.parquet
waveforms.zarr
timestamped_ultrasound_frames.parquet
```

至少校验 aligned / candidates / records SHA256 before/after。

# 26. Tests FIRST

必须先测试：

T01 deterministic event id
T02 one frame one event
T03 unique exact enrichment
T04 ambiguous event preserved
T05 ambiguous selected locator invalid
T06 OOT preserved
T07 timestamp unavailable preserved
T08 no timestamp fallback
T09 missing selected locator
T10 duplicated selected locator
T11 whitelist only
T12 soc_dod semantics
T13 raw dq/dv unchanged
T14 waveform locator preserved
T15 no waveform samples
T16 candidate relation
T17 candidate count invariant
T18 boundary propagation
T19 sync error propagation
T20 validated_sync false
T21 event quality mapping
T22 analysis eligibility
T23 row order
T24 multi-ultrasound asset
T25 multi-electrical asset
T26 input immutability
T27 manifest/report contract
T28 Zarr locator range synthetic
T29 current real integration
T30 real ambiguity regression
T31 golden frames 0/1000/2000/3000/3998

# 27. Current real ambiguity regression

当前已知 BRW-010 ambiguous frames：

```text
691
1914
2094
3998
```

这些 MeasurementEvents 必须存在，并满足：

```text
analysis_eligible=false
selected electrical state=null
candidate relation preserved
```

如果真实 artifact 已变化，先报告原因，不随意修改 expected。

# 28. Golden audit

抽查 frame：

```text
0
1000
2000
3000
3998
```

unique frames：独立确认 selected locator 对 records exact join 后 cycle/step/voltage/current/capacity 一致。

frame 3998：当前预期 ambiguous，event 必须存在、electrical state null、candidate evidence preserved。

# 29. Scientific semantics

必须明确：

```text
MeasurementEvent != validated physical ground truth
matching_performed = true
validated_sync = false
anchor_status = PROVISIONAL
```

# 30. BRW-012 handoff

BRW-011 完成后，后续 scientific analysis 优先消费：

```text
measurement_events.parquet
```

不要每次重新 join ultrasound + electrical。

# 31. Scope guard

严格禁止：

- rerun synchronization
- nearest timestamp lookup
- drift correction
- interpolation
- waveform filtering
- TOF extraction
- FFT physical features
- SOC/SOH modeling
- ML
- Agent
- UI

# 32. Quality gates

完成后：

```bash
pytest
ruff check <本次修改文件>
ruff format --check <本次修改文件>
mypy <可运行范围>
git diff --check
```

full mypy 如仍被既有 NumPy/Python stub 阻断，记录 BRW-TECH issue。

# 33. Final handoff

最终必须报告：

## Status
PASS / PARTIAL / FAIL

## Files changed

## Input counts
Aligned / Candidates / Electrical

## Event quality summary
READY / AMBIGUOUS_SYNC / OUT_OF_TOLERANCE / TIMESTAMP_UNAVAILABLE

## Analysis eligibility
count / fraction

## Electrical enrichment
fields / coverage

## Ambiguity preservation
列出真实 ambiguous event

## Golden frames
0 / 1000 / 2000 / 3000 / 3998

## Canonical outputs
measurement_events.parquet / measurement_event_candidates.parquet / measurement_event_manifest.json

## Input integrity

## Tests
pytest / coverage / ruff / format / mypy / git diff

## Scientific semantics
matching_performed=true / validated_sync=false / anchor remains provisional

## Scope confirmation
No rematching / No interpolation / No drift correction / No feature extraction

完成后停止，不进入 BRW-012。
