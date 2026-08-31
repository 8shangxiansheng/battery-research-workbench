# BRW-009 — Timestamp Construction Engine

把整个任务包放到：

```text
battery-research-workbench/
└── tasks/
    └── BRW-009/
```

执行顺序：

```text
Inspect
→ Tests RED
→ Clock / Timestamp schemas
→ Per-asset timestamp construction
→ Multi-asset handling
→ Diagnostics / provenance
→ Persistence
→ Real CELL_001 validation
→ Final gate
```

---

## BRW-009 的唯一目标

把：

```text
BRW-008 time_anchors.json
+
BRW-005 frames.parquet
```

转换为：

```text
per-frame provisional absolute timestamps
```

形成一个统一、确定性、可审计的 Timestamp Engine。

---

## 这一轮仍然不是 synchronization

禁止：

```text
nearest electrical timestamp lookup
electrical row matching
candidate electrical row search
cycle mapping
step mapping
sync_error_s against electrical
duplicate electrical timestamp resolution
drift fitting
MeasurementEvent
```

这些属于：

```text
BRW-010 Synchronization
BRW-011 MeasurementEvent
```

---

## 当前核心语义

如果 BRW-008 选中的 anchor 是：

```text
anchor_datetime = T0
elapsed_time_s_at_anchor = e0
```

BRW-009 V1 使用：

```text
provisional_absolute_timestamp
=
T0 + (elapsed_time_s - e0)
```

当前 U001：

```text
T0 = 2024-01-06 09:52:31
e0 = 0.0
```

第一帧：

```text
elapsed = 0.031217
→ 2024-01-06 09:52:31.031217
```

---

## 科学约束

```text
PROVISIONAL timestamp
≠
VERIFIED synchronized timestamp
```

BRW-009 只能生成“基于已选 anchor 的时间坐标”。

不能证明它与 Electrical record 已正确匹配。
