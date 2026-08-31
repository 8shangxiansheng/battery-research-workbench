# BRW-003 Master Vibe Coding Prompt

你正在维护 `battery-research-workbench`，当前架构版本为 V1.1。

## 0. 先执行阅读，不要直接改代码

在进行任何修改前，必须依次阅读：

1. `AGENTS.md`
2. `README.md`
3. `docs/development-plan.md`
4. `docs/tech-stack.md`
5. `docs/data_contract/electrical_xlsx.md`
6. `docs/data_contract/manifests.md`
7. `data/raw/manifests/batteries.csv`
8. `data/raw/manifests/experiments.csv`
9. `data/raw/manifests/data_assets.csv`
10. 现有：
   - `src/battery_workbench/domain/`
   - `src/battery_workbench/io/electrical/`
   - `src/battery_workbench/io/experiment/`
   - `src/battery_workbench/storage/`
   - `tests/`

然后检查 `CELL_001` 下当前已经存在的真实 Electrical XLSX 文件以及它们对应的 Experiment / DataAsset。

**不要假设当前一定只有一个 XLSX，也不要假设一个 XLSX 等于一个 Cycle。**
当前用户已经放入第一块电池的两次循环/实验相关数据，必须根据实际 manifest + 文件内容确认组织方式。

---

# 1. Task

实现：

> **BRW-003 — Electrical XLSX Parser**

目标是将一个 Experiment 下的一个或多个 Electrical XLSX `DataAsset`
可靠解析、标准化并保存为 Parquet，同时保持完整 provenance。

BRW-003 只负责 Electrical 数据。

不要实现：

- 超声解析
- 双模态同步
- TOF / FFT 等声学算法
- SOH/SOC 模型
- Agent
- JupyterLab UI

---

# 2. Architecture constraints

必须遵循：

```text
Battery
  ↓
Experiment
  ↓
Electrical DataAsset(s)
  ↓
Electrical XLSX Parser
  ↓
Standardized Electrical Tables
```

Cycle 不是文件身份，也不是跨文件同步主键。

一个 Experiment 可以有：

```text
1..N Electrical XLSX DataAssets
```

一个 XLSX 可以包含：

```text
1..N Cycles
```

必须保留原始 Cycle / Step 编号，不得擅自重新编号。

---

# 3. Required canonical output

为每个 Experiment 输出：

```text
data/processed/electrical/
└── {battery_id}/
    └── {experiment_id}/
        ├── records.parquet
        ├── cycles.parquet
        ├── steps.parquet
        ├── aux_temperature.parquet   # source exists 时生成
        ├── aux_voltage.parquet       # source exists 时生成
        └── parser_manifest.json
```

如果同一个 Experiment 包含多个 XLSX：

- 允许合并到同一个标准表；
- 每行必须保留 `electrical_asset_id`；
- 必须保留来源行号；
- 必须按 canonical timestamp 排序；
- 不允许静默覆盖/去重重叠数据；
- 如发现无法安全合并的时间重叠，必须显式报告 validation error 或 warning，并记录在 manifest。

---

# 4. Canonical records schema

`records.parquet` 至少应支持以下字段（如果源文件存在）：

```text
battery_id                 string
experiment_id              string
electrical_asset_id        string
source_file                string
source_sheet               string
source_row_index           int

record_index_raw           int | null
cycle_index_raw            int | null
step_index_raw             int | null
step_type_raw              string | null

timestamp                  datetime
elapsed_time_s             float | null
step_time_s                float | null

current_a                  float | null
voltage_v                  float | null
capacity_ah                float | null
charge_capacity_ah         float | null
discharge_capacity_ah      float | null

energy_wh                  float | null
charge_energy_wh           float | null
discharge_energy_wh        float | null
power_w                    float | null

dqdv_mah_per_v             float | null
contact_resistance_mohm    float | null
soc_dod_percent            float | null
```

注意：

- 不要删除原始中文列名信息。
- `parser_manifest.json` 必须记录 canonical field ↔ source column mapping。
- 不存在的字段应保持 null/absence，而不是编造。
- `SOC/DOD(%)` 在没有明确确认是 SOC 还是 DOD 前，canonical 名称保持 `soc_dod_percent`，不要擅自解释为 `soc_percent`。

---

# 5. Supporting tables

## cycles.parquet

保留原 Cycle Sheet 中能够可靠解析的 cycle-level 信息，并至少增加：

```text
battery_id
experiment_id
electrical_asset_id
source_row_index
cycle_index_raw
```

## steps.parquet

至少：

```text
battery_id
experiment_id
electrical_asset_id
source_row_index
cycle_index_raw
step_index_raw
step_type_raw
```

以及能够可靠解析的 step-level capacity / current / voltage / DCIR / time 字段。

## aux_temperature.parquet

如果存在 `auxTemp`：

至少：

```text
battery_id
experiment_id
electrical_asset_id
source_row_index
timestamp
temperature_channel
temperature_c
```

## aux_voltage.parquet

如果存在 `auxVol`：

至少：

```text
battery_id
experiment_id
electrical_asset_id
source_row_index
timestamp
voltage_channel
voltage_v
```

---

# 6. Suggested implementation structure

优先最小化实现，推荐：

```text
src/battery_workbench/io/electrical/
├── __init__.py
├── custom_excel.py
├── schemas.py
├── column_mapping.py
├── validation.py
└── service.py
```

其中职责：

### custom_excel.py
只处理具体 Excel workbook / sheet 的读取。

### schemas.py
定义 parser result / canonical schema，不要放业务逻辑。

### column_mapping.py
集中维护：

```text
source Chinese column
    ↓
canonical field
```

禁止在多个函数中到处散落硬编码列名。

### validation.py
负责：
- required sheets
- required columns
- timestamp monotonicity
- cycle/step consistency
- duplicate/overlap diagnostics
- null/type diagnostics

### service.py
提供高层 API，例如：

```python
parse_electrical_asset(...)
parse_electrical_experiment(...)
write_electrical_parquet(...)
```

Agent / FastAPI / Notebook 将来只调用 service，不直接操作 openpyxl。

---

# 7. Parser requirements

必须：

1. 原始 XLSX 只读。
2. 使用 manifest 的 `DataAsset` 身份，不以文件名作为唯一身份。
3. 支持一个 Experiment 多个 Electrical XLSX。
4. 支持一个 XLSX 多个 Cycle。
5. 保留 raw cycle / step index。
6. 保留 source row provenance。
7. 解析失败时给出明确异常。
8. 不允许 silently skip invalid rows。
9. 允许 optional sheet 缺失，但 manifest 必须记录。
10. 输出 Parquet 可被重新读取并保持关键 dtype。

---

# 8. Tests FIRST

在实现 parser 主逻辑前，先补测试。

必须包含：

## A. Synthetic unit tests

创建一个最小 synthetic XLSX，至少包含：

```text
record
cycle
step
auxTemp
```

且包含两个 cycle。

验证：

- sheet 识别
- 中文列映射
- timestamp 解析
- cycle raw value 保留
- step raw value 保留
- current / voltage / capacity 数值一致
- provenance columns 正确
- Parquet round-trip

## B. Real-data integration test

针对当前仓库中 `CELL_001` 的真实 Electrical XLSX：

不要把完整原始文件复制进测试 fixture。

测试必须：

- 通过 manifest 找到 DataAsset
- 解析所有当前真实 Electrical XLSX
- 验证至少：
  - record 行数 > 0
  - timestamp 非空
  - timestamp non-decreasing（每个 asset 内）
  - cycle_index_raw 非空比例合理
  - 当前两次循环/数据中实际存在的 cycle IDs 被正确读出
  - required source columns 映射正确
  - parser 不修改原文件 SHA256

## C. Golden tests

从真实 XLSX 中独立挑选：

- 第一条 record
- 中间一条 record
- 最后一条 record
- 至少各 Cycle 一条 record

将人工/独立读取确认的关键原始值写入：

```text
tests/golden/electrical_expected.json
```

例如：

```json
{
  "asset_id": "...",
  "checks": [
    {
      "source_row_index": 2,
      "cycle_index_raw": 1,
      "voltage_v": 3.123,
      "current_a": 1.0
    }
  ]
}
```

**Golden expected values 不允许通过被测试 parser 自己生成。**

---

# 9. Validation gates

BRW-003 完成必须满足：

### Data integrity
- [ ] raw XLSX SHA256 before == after
- [ ] record count 可解释
- [ ] cycle raw IDs 保留
- [ ] step raw IDs 保留
- [ ] timestamp 正确
- [ ] source provenance 完整

### Schema
- [ ] canonical names 集中定义
- [ ] original column mapping 写入 manifest
- [ ] optional fields 不编造

### Multi-file support
- [ ] 一个 Experiment 多 XLSX 能工作
- [ ] 每行保留 asset_id
- [ ] 时间重叠不会被静默覆盖

### Tests
- [ ] synthetic unit tests
- [ ] golden tests
- [ ] current real-data integration tests
- [ ] parquet round-trip test
- [ ] full `pytest` passes

---

# 10. Required parser manifest

生成：

```text
parser_manifest.json
```

至少：

```json
{
  "battery_id": "...",
  "experiment_id": "...",
  "parser": "custom_excel",
  "parser_version": "...",
  "source_assets": [],
  "source_sha256": {},
  "sheets_found": {},
  "column_mappings": {},
  "row_counts": {},
  "cycle_ids_raw": [],
  "step_ids_raw": [],
  "timestamp_min": "...",
  "timestamp_max": "...",
  "warnings": [],
  "output_files": {}
}
```

不要记录臆测出的物理含义。

---

# 11. QA artifacts

BRW-003 本身只需要生成最小数据 QA，不进入正式 BRW-004 visualization。

至少生成或在 parser manifest 中统计：

```text
records count
cycle IDs
step IDs
timestamp start/end
null counts
duplicate timestamp count
per-asset row count
```

不要在 BRW-003 大量开发图表 UI。

---

# 12. Coding style

- 尽量小改动。
- 不重构无关模块。
- public API 加类型。
- scientific/data validation 逻辑不能藏在 notebook。
- 不把 pandas DataFrame schema 规则只写在 prompt/comment 中。
- 错误信息必须包含 asset_id/file/sheet/column 等上下文。

---

# 13. Before finishing

必须实际运行：

```bash
pytest
ruff check src tests apps scripts
```

如果项目已有 mypy 配置，再运行：

```bash
mypy src
```

并实际用当前 `CELL_001` 的真实 Electrical DataAsset 执行一次 parser。

检查生成：

```text
records.parquet
cycles.parquet
steps.parquet
aux_temperature.parquet (if available)
aux_voltage.parquet (if available)
parser_manifest.json
```

然后用 pandas 重新读取 `records.parquet`。

---

# 14. Final response format

完成后不要只说“done”。

必须报告：

## Files changed
列出所有新增/修改文件。

## Implementation
说明：
- XLSX 如何读取
- 如何做 column mapping
- 多文件如何处理
- provenance 如何保留

## Current real data
报告当前 `CELL_001`：
- 解析了几个 XLSX assets
- records 行数
- cycle raw IDs
- timestamp range
- optional sheets
- warnings

## Tests
逐项列出执行命令及结果。

## Outputs
列出生成的 Parquet / manifest 路径。

## Limitations
明确当前仍未实现：
- BRW-004
- ultrasound
- synchronization
- ML
- Agent

如果任何验收失败，不要掩盖；说明失败项和原因。
