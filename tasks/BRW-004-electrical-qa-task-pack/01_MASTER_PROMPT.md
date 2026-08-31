# BRW-004 Master Vibe Coding Prompt

你正在维护 `battery-research-workbench`，架构 V1.1。
BRW-003 已完成并通过。

## 0. 先读，不要直接改代码

按顺序读取：

1. `AGENTS.md`
2. `README.md`
3. `docs/development-plan.md`
4. `docs/tech-stack.md`
5. `docs/data_contract/electrical_xlsx.md`
6. `tasks/BRW-003/03_OUTPUT_CONTRACT.md`（若存在）
7. 当前 Electrical QA 相关代码
8. 当前 `data/processed/electrical/` 下真实输出
9. 当前 `parser_manifest.json`
10. 当前 tests

第一轮只 Inspect。

# 1. Task

实现：

> **BRW-004 — Electrical QA**

对 BRW-003 已生成的标准化 Electrical 数据做自动质量检查，
输出机器可读 JSON、人工可读 HTML、QA 图和异常表。

不要实现：

- parser 重构
- ultrasound
- multimodal synchronization
- ML
- Agent
- JupyterLab UI

# 2. Input boundary

正式 QA engine 只读取：

```text
records.parquet
cycles.parquet
steps.parquet
aux_temperature.parquet
aux_voltage.parquet
parser_manifest.json
```

不要重新把 XLSX 作为主流程数据源。

# 3. QA dimensions

## 3.1 Schema

检查：

```text
required columns
optional columns
dtype
provenance columns
timestamp dtype
cycle/step availability
```

输出：

```text
schema_status
missing_required_columns
missing_optional_columns
dtype_mismatches
```

## 3.2 Completeness

统计：

```text
row_count
null_count
null_ratio
```

重点：

```text
timestamp
cycle_index_raw
step_index_raw
current_a
voltage_v
capacity_ah
soc_dod_percent
dqdv_mah_per_v
contact_resistance_mohm
```

不要因为 `step_boundary_raw`、`lgd_raw` 大量 null 就自动 FAIL。

## 3.3 Temporal

必须：

```text
timestamp_min
timestamp_max
duration_s
is_monotonic_non_decreasing
duplicate_timestamp_count
duplicate_timestamp_groups
largest_gap_s
median_interval_s
interval_distribution
```

duplicate timestamps 只报告，不删除。

尽可能标记：

```text
likely_boundary_duplicate
```

## 3.4 Cycle QA

每 Cycle 输出：

```text
cycle_index_raw
start_timestamp
end_timestamp
records_count
charge_capacity_ah
discharge_capacity_ah
capacity_retention_percent
coulombic_efficiency_percent
charge_energy_wh
discharge_energy_wh
temperature_min_c
temperature_max_c
```

并检查：

- cycle IDs
- cycle 时间重叠
- records 时间范围 vs cycle table
- record-derived summary vs cycle table

## 3.5 Step QA

每个：

```text
cycle_index_raw + step_index_raw
```

输出：

```text
step_type_raw
start_timestamp
end_timestamp
records_count
duration_s
current_min/max/median
voltage_min/max
capacity_start/end
```

检查：

- step 顺序
- step duration
- step type consistency
- records vs steps time range

## 3.6 Physical-range QA

只做 configurable engineering sanity bounds，不把阈值当物理定律。

默认 warning：

```text
voltage
current
temperature
capacity
soc_dod_percent
```

全部阈值放进：

```text
configs/electrical_qa.yaml
```

## 3.7 Cross-table consistency

检查：

```text
records ↔ cycles
records ↔ steps
records ↔ aux_temperature
records ↔ aux_voltage
```

至少报告：

- ID coverage
- timestamp coverage
- nearest timestamp match rate
- summary differences

# 4. Required figures

至少 8 张：

```text
F01 voltage_vs_time.png
F02 current_vs_time.png
F03 capacity_vs_time.png
F04 temperature_vs_time.png
F05 voltage_current_vs_time.png
F06 cycle_capacity.png
F07 step_timeline.png
F08 dqdv_vs_voltage.png
```

要求：

- axis label + unit
- title 包含 battery / experiment
- 不隐藏异常点
- 不自动平滑原始 dQ/dV
- optional data 缺失时显式 unavailable

# 5. JSON report contract

```json
{
  "battery_id": "...",
  "experiment_id": "...",
  "qa_version": "0.1.0",
  "inputs": {},
  "summary": {},
  "schema": {},
  "completeness": {},
  "temporal": {},
  "cycles": [],
  "steps": [],
  "cross_table": {},
  "anomalies": [],
  "warnings": [],
  "status": "PASS|PASS_WITH_WARNINGS|FAIL",
  "artifacts": {}
}
```

# 6. Status rules

## FAIL

例如：

- records empty
- required column missing
- timestamp completely invalid
- critical dtype prevents analysis
- cycles/steps completely unlinkable

## PASS_WITH_WARNINGS

例如：

- duplicate timestamps
- optional aux missing
- isolated null/outlier
- cycle IDs non-contiguous
- boundary ambiguities

## PASS

无 critical issue 且无重要 warnings。

当前真实数据有 duplicate timestamps，通常应为：

```text
PASS_WITH_WARNINGS
```

不是 FAIL。

# 7. Implementation structure

推荐：

```text
src/battery_workbench/electrical/qa/
├── __init__.py
├── schemas.py
├── checks.py
├── temporal.py
├── cycles.py
├── steps.py
├── cross_table.py
├── anomalies.py
├── figures.py
├── report.py
└── service.py
```

# 8. Config

新增：

```text
configs/electrical_qa.yaml
```

默认示例：

```yaml
electrical_qa:
  version: "0.1.0"

  temporal:
    duplicate_timestamps_are_fatal: false
    large_gap_warning_s: 5.0

  physical_bounds:
    voltage_v:
      min: 0.0
      max: 5.0
    current_a:
      min: -30.0
      max: 30.0
    temperature_c:
      min: -20.0
      max: 80.0

  cross_table:
    timestamp_tolerance_s: 1.0
    numeric_relative_tolerance: 0.01
```

# 9. Tests FIRST

必须：

1. perfect synthetic → PASS
2. duplicate timestamps → PASS_WITH_WARNINGS
3. missing required column → FAIL
4. missing optional auxTemp → PASS_WITH_WARNINGS
5. non-monotonic timestamp
6. large gap
7. cycle mismatch
8. step mismatch
9. physical outlier
10. JSON contract
11. HTML report
12. 8 required figures
13. current real-data integration
14. input Parquet SHA256 before/after unchanged

# 10. Current known baseline

当前 BRW-003 已验证：

```text
records = 39996
cycles = 2
steps = 10
aux_temperature = 39996
aux_voltage = 39996

cycle IDs = [1,2]
step IDs = [1,2,3,4,5]

timestamp:
2024-01-06 09:52:31
→
2024-01-06 20:58:54

duplicate timestamps = 12
```

Agent 必须先确认当前仓库真实数据仍与此一致。

# 11. Anomaly object

建议：

```json
{
  "code": "DUPLICATE_TIMESTAMP",
  "severity": "warning",
  "scope": "records",
  "message": "...",
  "count": 12,
  "metadata": {}
}
```

severity：

```text
info
warning
critical
```

# 12. HTML sections

必须：

```text
1 Experiment Overview
2 Input / Provenance
3 QA Status
4 Schema
5 Missing Data
6 Temporal Quality
7 Cycle Summary
8 Step Summary
9 Electrical Ranges
10 Cross-table Consistency
11 Anomalies / Warnings
12 Figures
13 QA Configuration
14 Software / Version Provenance
```

# 13. Before finish

运行：

```bash
pytest
ruff check <本次修改文件>
ruff format --check <本次修改文件>
mypy src
```

全仓已有 lint debt 时：

- 不越界修
- 报告 existing debt
- 不新增 lint debt

然后真实运行当前 CELL_001 experiment。

# 14. Final handoff

必须报告：

## Status
PASS / PARTIAL / FAIL

## Files changed

## QA implementation

## Current real-data result

至少：
- records
- cycles
- steps
- timestamp range
- duplicate timestamps
- null summary
- physical ranges
- cross-table findings
- final QA status

## Artifacts

JSON / HTML / figures / tables。

## Tests

命令 + 结果。

## Known limitations

明确未做：

- Ultrasound
- Synchronization
- ML
- Agent
- UI
