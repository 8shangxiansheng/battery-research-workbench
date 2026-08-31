# Current BRW-011 Baseline

```text
CELL_001 / EXP_001
```

Upstream semantic state：

```text
matching_performed = true
validated_sync = false
anchor_status = PROVISIONAL
sync_semantics = MATCHED_USING_PROVISIONAL_TIMEBASE
```

Known ambiguous regression frames：

```text
691
1914
2094
3998
```

这些必须继续存在为 MeasurementEvents，不得 silent resolve。

Expected grain：

```text
measurement_event rows = aligned ultrasound rows ≈ 3999
```

实际 artifact 是 source of truth。
