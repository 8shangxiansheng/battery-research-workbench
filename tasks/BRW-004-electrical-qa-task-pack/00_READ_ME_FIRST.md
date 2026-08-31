# BRW-004 — Electrical QA Task Pack

把整个 `BRW-004/` 文件夹放到仓库：

```text
battery-research-workbench/
└── tasks/
    └── BRW-004/
```

然后让 Coding Agent：

1. 先读仓库根目录 `AGENTS.md`
2. 再读 `tasks/BRW-004/01_MASTER_PROMPT.md`
3. 先 Inspect
4. 再 tests-first 实现

## 唯一目标

对 BRW-003 生成的标准化 Electrical Parquet 做：

```text
Schema QA
→ Completeness QA
→ Temporal QA
→ Cycle / Step QA
→ Physical-range QA
→ Cross-table consistency QA
→ Electrical QA Report
```

不修改 Parser，不做 Ultrasound / Synchronization / ML / Agent / UI。

## 输入

```text
data/processed/electrical/{battery_id}/{experiment_id}/
├── records.parquet
├── cycles.parquet
├── steps.parquet
├── aux_temperature.parquet
├── aux_voltage.parquet
└── parser_manifest.json
```

## 输出

```text
data/artifacts/{battery_id}/{experiment_id}/electrical_qa/
├── electrical_qa_report.json
├── electrical_qa_report.html
├── figures/
│   ├── voltage_vs_time.png
│   ├── current_vs_time.png
│   ├── capacity_vs_time.png
│   ├── temperature_vs_time.png
│   ├── voltage_current_vs_time.png
│   ├── cycle_capacity.png
│   ├── step_timeline.png
│   └── dqdv_vs_voltage.png
└── tables/
    ├── cycle_summary.csv
    ├── step_summary.csv
    └── anomalies.csv
```
