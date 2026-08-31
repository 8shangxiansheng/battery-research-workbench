# Expected Repository Changes

BRW-003 正常情况下主要修改：

```text
src/battery_workbench/io/electrical/
├── custom_excel.py
├── schemas.py
├── column_mapping.py
├── validation.py
└── service.py

src/battery_workbench/storage/
└── parquet.py

tests/
├── unit/
│   ├── test_electrical_parser.py
│   ├── test_electrical_mapping.py
│   └── test_electrical_parquet.py
├── integration/
│   └── test_current_electrical_assets.py
└── golden/
    └── electrical_expected.json
```

可能更新：

```text
docs/data_contract/electrical_xlsx.md
docs/development-plan.md
```

不应大规模修改：

```text
ultrasound/
synchronization/
agent/
ml/
apps/jupyterlab-extension/
```
