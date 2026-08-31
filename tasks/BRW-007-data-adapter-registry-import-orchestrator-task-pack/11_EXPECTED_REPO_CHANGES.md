# Expected Repository Changes

主要新增：

```text
src/battery_workbench/io/adapters/
├── __init__.py
├── base.py
├── registry.py
├── electrical.py
└── ultrasound.py
```

可能新增：

```text
src/battery_workbench/io/experiment/schemas.py
```

重点修改：

```text
src/battery_workbench/io/experiment/importer.py
```

tests：

```text
tests/unit/
├── test_adapter_registry.py
├── test_experiment_import_plan.py
├── test_experiment_importer.py
└── test_adapter_failure_policy.py

tests/integration/
└── test_current_experiment_import_plan.py
```

不应大规模修改：

```text
io/electrical/
io/ultrasound/
electrical/qa/
ultrasound/qa/
synchronization/
analysis/
ml/
agent/
apps/
```
