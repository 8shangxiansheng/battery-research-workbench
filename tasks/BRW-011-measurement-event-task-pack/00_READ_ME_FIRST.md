# BRW-011 — MeasurementEvent Canonical Multimodal Layer

把整个任务包放到：

```text
battery-research-workbench/
└── tasks/
    └── BRW-011/
```

执行顺序：

```text
Inspect
→ Tests RED
→ MeasurementEvent schema
→ Unique-match enrichment
→ Ambiguous-event preservation
→ Multi-asset support
→ Persistence
→ QA/report
→ Real CELL_001 validation
→ Final gate
```

## BRW-011 的唯一目标

把：

```text
BRW-010 aligned_ultrasound_frames.parquet
+
BRW-010 synchronization_candidates.parquet
+
BRW-003 electrical records.parquet
+
BRW-005 waveform locators
```

统一组织成：

```text
MeasurementEvent
```

## 核心原则

```text
1 MeasurementEvent = 1 ultrasound frame
```

BRW-011 不再做时间匹配，只消费 BRW-010 已确定的结果。

Ambiguous 事件必须保留，但 selected electrical state 必须为 null。
