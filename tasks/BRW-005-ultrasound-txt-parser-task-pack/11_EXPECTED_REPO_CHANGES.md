# Expected Repository Changes

BRW-005 正常主要修改：

```text
src/battery_workbench/io/ultrasound/
├── __init__.py
├── custom_txt.py
├── schemas.py
├── validation.py
├── service.py
└── manifest.py

src/battery_workbench/storage/
└── zarr_store.py

tests/unit/
├── test_ultrasound_line_parser.py
├── test_ultrasound_validation.py
├── test_ultrasound_zarr.py
└── test_ultrasound_multi_asset.py

tests/integration/
└── test_current_ultrasound_assets.py

tests/golden/
└── ultrasound_expected.json
```

可能更新：

```text
docs/data_contract/ultrasound_txt.md
docs/development-plan.md
README.md
```

不应大规模修改：

```text
electrical/
synchronization/
analysis/
ml/
agent/
apps/
```
