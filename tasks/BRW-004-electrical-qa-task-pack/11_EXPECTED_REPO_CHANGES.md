# Expected Repository Changes

主要新增：

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

configs/
└── electrical_qa.yaml

tests/unit/
├── test_electrical_qa_schema.py
├── test_electrical_qa_temporal.py
├── test_electrical_qa_cycles.py
├── test_electrical_qa_steps.py
├── test_electrical_qa_cross_table.py
├── test_electrical_qa_figures.py
└── test_electrical_qa_report.py

tests/integration/
└── test_current_electrical_qa.py
```

可能更新：

```text
docs/development-plan.md
README.md
```

不应大规模修改：

```text
io/electrical/
ultrasound/
synchronization/
agent/
ml/
apps/
```
