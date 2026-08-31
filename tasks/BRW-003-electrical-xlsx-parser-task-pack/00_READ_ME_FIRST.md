# BRW-003 — Electrical XLSX Parser Task Pack

把整个 `BRW-003/` 文件夹放到你的仓库，例如：

```text
battery-research-workbench/
└── tasks/
    └── BRW-003/
        ├── 00_READ_ME_FIRST.md
        ├── 01_MASTER_PROMPT.md
        └── ...
```

然后在 Cursor / Claude Code / Codex 中：

1. 打开仓库根目录。
2. 让 Coding Agent **先读取 `AGENTS.md`**。
3. 再读取 `tasks/BRW-003/01_MASTER_PROMPT.md`。
4. 明确告诉它：当前 `CELL_001` 中已经有两次循环/实验相关的真实电学 XLSX，必须先检查现有 manifest 和真实文件，不能猜路径或字段。
5. 让它严格按照 Prompt 执行。
6. 不要一次同时做 BRW-004、超声 Parser、同步、Agent/UI。

## BRW-003 的唯一目标

```text
Electrical XLSX DataAsset(s)
        ↓
Schema inspection
        ↓
Canonical parsing
        ↓
Validation
        ↓
Standardized Parquet
        ↓
Parser manifest / provenance
```

不做：

- Ultrasound parsing
- Electrical–Ultrasound synchronization
- SOH/SOC prediction
- ML
- Agent
- JupyterLab UI

## 完成后的最重要产物

```text
data/processed/electrical/
└── CELL_001/
    └── EXP_xxx/
        ├── records.parquet
        ├── cycles.parquet
        ├── steps.parquet
        ├── aux_temperature.parquet   # 若原文件存在
        ├── aux_voltage.parquet       # 若原文件存在
        └── parser_manifest.json
```

每一行标准化数据都必须能追溯回：

```text
battery_id
experiment_id
electrical_asset_id
source_file
source_sheet
source_row_index
```
