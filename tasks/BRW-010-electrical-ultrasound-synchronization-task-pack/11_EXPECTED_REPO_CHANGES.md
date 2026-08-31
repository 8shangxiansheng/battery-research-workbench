# Expected Repository Changes

优先扩展：

```text
src/battery_workbench/synchronization/
```

推荐新增：

```text
electrical_index.py
matcher.py
boundary.py
sync_schemas.py
sync_validation.py
sync_persistence.py
sync_report.py
```

如果现有模块结构已有等价职责，
可以合并，避免碎文件。

配置：

```text
configs/synchronization.yaml
```

tests：

```text
tests/unit/
├── test_electrical_timestamp_index.py
├── test_nearest_matcher.py
├── test_sync_ambiguity.py
├── test_sync_boundary.py
├── test_sync_persistence.py
└── test_sync_report.py

tests/integration/
└── test_current_synchronization.py
```

不应修改 parser scientific/data behavior。
