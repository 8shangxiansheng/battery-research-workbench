# Expected Repository Changes

推荐新增：

```text
src/battery_workbench/multimodal/
├── __init__.py
├── schemas.py
├── event_id.py
├── electrical_index.py
├── builder.py
├── validation.py
├── persistence.py
└── report.py
```

配置：

```text
configs/measurement_event.yaml
```

Tests：

```text
tests/unit/
├── test_measurement_event_id.py
├── test_measurement_event_builder.py
├── test_measurement_event_ambiguity.py
├── test_measurement_event_validation.py
└── test_measurement_event_persistence.py

tests/integration/
└── test_current_measurement_events.py
```

不应修改 parser 或 synchronization matcher scientific behavior。
