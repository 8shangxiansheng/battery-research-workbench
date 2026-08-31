# Expected Repository Changes

推荐新增/实现：

```text
src/battery_workbench/synchronization/
├── __init__.py
├── schemas.py
├── anchors.py
├── evidence.py
├── validation.py
├── persistence.py
└── service.py
```

配置：

```text
configs/time_anchor.yaml
```

tests：

```text
tests/unit/
├── test_time_anchor_schemas.py
├── test_time_anchor_resolution.py
├── test_time_anchor_validation.py
└── test_time_anchor_persistence.py

tests/integration/
└── test_current_time_anchor.py
```

不应修改科学逻辑：

```text
io/electrical/
io/ultrasound/
electrical/qa/
ultrasound/qa/
```
