# OSI-001 Master Vibe Coding Prompt

你正在维护：

```text
battery-research-workbench
```

当前核心任务 BRW-003～006 已通过。

现在执行：

> **OSI-001 — BEEP + cellpy Neware Compatibility Spike**

本任务是 Open Source Integration Spike，不是功能重写。

---

# 0. 开始前必须阅读

按顺序：

1. `AGENTS.md`
2. `README.md`
3. `docs/development-plan.md`
4. `docs/tech-stack.md`
5. `docs/data_contract/electrical_xlsx.md`
6. `tasks/BRW-003/`
7. `tasks/BRW-004/`
8. 当前：
   - `src/battery_workbench/io/electrical/`
   - `src/battery_workbench/electrical/qa/`
   - `data/raw/manifests/data_assets.csv`
   - `data/processed/electrical/CELL_001/EXP_001/`
9. 当前真实 Neware XLSX
10. 当前 `pyproject.toml` / uv 配置 / Python version

---

# 1. 不要先假设第三方一定可用

需要实际验证：

```text
Custom BRW Parser
vs
cellpy
vs
BEEP
```

尤其要区分：

```text
“支持 Neware”
```

与：

```text
“支持当前这份 Neware 多-sheet XLSX”
```

这不是同一件事。

---

# 2. Environment strategy

本轮不要修改主 `.venv`。

创建：

```text
experiments/open_source_neware/
```

并创建隔离 uv 环境：

```bash
uv venv --python 3.13 experiments/open_source_neware/.venv
```

在该环境安装：

```bash
uv pip install --python experiments/open_source_neware/.venv/bin/python cellpy beep
```

macOS/Linux 路径按实际环境调整。

如果仓库已有 uv workspace 规范，
遵循现有规范，但仍保持 spike 与主 runtime 隔离。

---

# 3. Capture exact versions

必须输出：

```text
python version
cellpy version
beep version
numpy
pandas
scipy
matplotlib
```

生成：

```text
experiments/open_source_neware/environment_report.json
```

不要只写“latest”。

---

# 4. cellpy compatibility investigation

重点测试三种路径。

## Path A — native Neware loader

检查 cellpy 当前：

```text
neware_txt
```

loader 是否接受当前 XLSX。

不要因为名字是 `neware_txt` 就猜它支持 XLSX。

记录：

```text
SUCCESS
PARTIAL
UNSUPPORTED_FORMAT
ERROR
```

及完整异常摘要。

---

## Path B — custom loader

检查：

```text
instrument="custom"
```

或当前 cellpy 对应 API，
是否能通过 XLS/XLSX query path + mapping 加载当前数据。

目标不是马上写完整 production mapping，
而是证明：

```text
能否把 record sheet 映射进 CellpyCell
```

最低验证：

```text
timestamp
cycle
step
current
voltage
capacity
```

---

## Path C — export bridge

如果 cellpy native loader 只适用于 csv/txt：

尝试构造一个非破坏性的 compatibility bridge：

```text
Current BRW records.parquet
        ↓
temporary canonical CSV
        ↓
cellpy
```

这只是 spike。

不要把 temporary CSV 放回 raw data。

---

# 5. cellpy capabilities to measure

如果加载成功，实际调用并记录：

```text
raw table
steps table
summary table
cycle selection
capacity-related helpers
plotting helpers
```

不要只 import 成功就判 compatible。

至少回答：

```text
Can load?
Can identify 2 cycles?
Can identify 10 steps?
Can reproduce charge/discharge capacity?
Can produce useful plot?
Can preserve/represent temperature?
Can preserve/represent aux voltage?
Can expose dQ/dV or help generate it?
```

---

# 6. BEEP compatibility investigation

先 Inspect 当前 BEEP API。

BEEP 官方声明支持 Neware，
但必须找到实际 Neware parser / datapath / expected source format。

不要使用 Maccor example 代替 Neware compatibility。

必须记录：

```text
Neware parser class/function
expected file format
required columns
direct XLSX support?
```

然后测试当前 XLSX。

---

# 7. BEEP fallback paths

如果直接 XLSX 不兼容，依次评估：

## Path A
能否对 Neware 的某种 export CSV/TXT 格式工作。

## Path B
能否从 BRW canonical records 导出临时 BEEP-compatible table。

## Path C
只使用 BEEP 后端：

```text
structure
interpolation
feature classes
model-related utilities
```

而保留 BRW-003 作为 loader。

---

# 8. Never replace provenance

即使 cellpy/BEEP 能加载数据，

Battery Research Workbench 的 canonical identity 仍然必须保留：

```text
battery_id
experiment_id
electrical_asset_id
source_file
source_row_index
cycle_index_raw
step_index_raw
```

第三方对象不能成为工作台唯一 source of truth。

---

# 9. Three-way comparison

以当前 BRW-003 Golden baseline 为 reference：

```text
records = 39996
cycles = 2
steps = 10
```

比较：

```text
Custom Parser
cellpy
BEEP
```

至少字段：

```text
record count
cycle count
step count

timestamp
current
voltage
capacity

charge capacity
discharge capacity

temperature
aux voltage
dQ/dV
contact resistance
SOC/DOD
```

---

# 10. Numeric Golden comparison

当前至少独立比较：

```text
Cycle 1 charge capacity
Cycle 1 discharge capacity
Cycle 2 charge capacity
Cycle 2 discharge capacity
```

reference：

```text
~11.0959 Ah
~11.0441 Ah
~11.0551/11.0552 Ah
~11.0083 Ah
```

以当前 BRW canonical output 为最终程序化 reference，
不要因文档四舍五入差异让测试错误失败。

再比较：

```text
first record
middle record
last record
```

的：

```text
timestamp
voltage
current
capacity
cycle
step
```

---

# 11. Plot comparison

如果第三方提供 plotting：

至少生成：

```text
cellpy_voltage_vs_time.png
cellpy_cycle_capacity.png
```

如果 BEEP 提供适用绘图/structured visualization，
生成对应最小图。

目的：

> 评估是否能减少 BRW 自己的 plotting workload。

不是要求第三方图取代 BRW-004 QA。

---

# 12. Scoring rubric

每个工具按 0～3：

```text
0 = unavailable
1 = possible but heavy adapter required
2 = useful with moderate adapter
3 = direct/high-value reuse
```

评分维度：

```text
Raw Neware XLSX loading
Record normalization
Cycle parsing
Step parsing
Capacity summary
Temperature support
Aux voltage support
dQ/dV support
Plotting
Batch analysis
Feature engineering
ML utility
Provenance fit
Maintenance/API quality
Integration complexity
```

---

# 13. Required recommendation categories

最后只能选择以下一种架构建议：

## A — Keep Custom, use cellpy analysis only

```text
BRW Parser
↓
BRW Canonical
↓
cellpy Adapter
↓
cellpy analysis/plots
```

## B — cellpy as primary electrical backend

只有 direct compatibility + Golden equivalence 足够好才允许推荐。

## C — Keep Custom + use BEEP downstream

```text
BRW Parser
↓
Canonical Adapter
↓
BEEP structuring/features
```

## D — Hybrid

例如：

```text
Custom BRW ingestion
cellpy battery analysis
BEEP feature/ML utilities
```

## E — Do not integrate yet

如果 compatibility/value 不足。

---

# 14. Do NOT do these in OSI-001

禁止：

- 删除 BRW-003
- 修改 BRW-003 Golden expected values 来迎合第三方
- 修改 raw XLSX
- 把 cellpy/BEEP object 写成核心 Domain model
- 迁移主项目 Python 3.13
- 改主 pyproject dependency
- 重写 BRW-004
- Ultrasound changes
- synchronization
- ML production integration
- Agent/UI integration

---

# 15. Required experiment code

建议：

```text
experiments/open_source_neware/
├── README.md
├── environment_report.json
├── inspect_cellpy.py
├── inspect_beep.py
├── compare_with_brw.py
├── results/
│   ├── cellpy_report.json
│   ├── beep_report.json
│   ├── comparison.json
│   ├── compatibility_matrix.csv
│   └── figures/
└── notes/
    ├── cellpy_api_notes.md
    └── beep_api_notes.md
```

本轮 experimental code 不放：

```text
src/battery_workbench/
```

除非是非常小的 read-only helper，
并且必要性明确。

---

# 16. Tests

至少：

## T01 Environment
Python 3.13 env exists and imports both packages.

## T02 Raw immutability
XLSX SHA256 before/after identical.

## T03 Custom baseline
读取现有 BRW outputs，确认 baseline。

## T04 cellpy direct load
记录成功或结构化失败。

## T05 cellpy custom/bridge
至少验证一种 fallback。

## T06 BEEP direct Neware path
找到真实 Neware API，实际尝试。

## T07 BEEP bridge/fallback
如 direct fail，尝试 canonical bridge。

## T08 Golden comparison
数值差异表。

## T09 Plot smoke test
第三方 plot 不崩溃。

## T10 Main repo regression
主项目：

```bash
pytest
```

仍然通过。

---

# 17. Final report

必须生成：

```text
experiments/open_source_neware/OSI-001_REPORT.md
```

结构：

## Executive conclusion

一句话：

```text
cellpy: ...
BEEP: ...
Recommended architecture: ...
```

## Environment

## Current Neware XLSX characteristics

## cellpy findings

## BEEP findings

## Three-way compatibility matrix

## Golden numeric comparison

## Plotting usefulness

## Development-effort impact

估计：

```text
Parser
Analysis
Plotting
Features/ML
```

各可减少多少“类别的自研工作”，
不要伪造精确人天。

## Risks

## Recommended integration architecture

## Explicitly rejected approaches

## Next task proposal

---

# 18. Final handoff response

向用户报告：

## Status

PASS / PARTIAL / FAIL

这里 PASS 的含义：

> Compatibility study 完成。

不是：

> 两个库必须兼容。

即使两个库都不兼容，
只要 spike 完整且结论有证据，也可以 PASS。

## cellpy result

## BEEP result

## Best integration path

## Files created

## Tests

## Raw integrity

## Main repository regression

## Proposed next step

完成后停止，不进行 production integration。
