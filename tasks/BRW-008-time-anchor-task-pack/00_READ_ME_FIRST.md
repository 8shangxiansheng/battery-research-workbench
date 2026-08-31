# BRW-008 — Experiment Time Anchor Foundation

把整个任务包放到：

```text
battery-research-workbench/
└── tasks/
    └── BRW-008/
```

执行顺序：

```text
Inspect
→ Tests RED
→ Anchor schemas
→ Evidence collection
→ Candidate resolution
→ Coverage plausibility
→ Persistence/report
→ Current real-data validation
→ Final gate
```

---

## BRW-008 的唯一目标

建立：

```text
Experiment reference window
+
per-asset TimeAnchorCandidate
+
anchor evidence/provenance
+
provisional anchor resolution
+
coverage plausibility diagnostics
```

为 BRW-009 Timestamp Engine 提供可靠输入。

---

## 这一轮不是完整同步

禁止：

```text
ultrasound frame ↔ electrical record matching
nearest timestamp matching
cycle mapping
step mapping
drift fitting
cross-correlation time alignment
MeasurementEvent
```

即：

```text
BRW-008 = anchor foundation
BRW-009 = timestamp engine
BRW-010 = synchronization
```

---

## 当前最重要的科学约束

当前 U001 manifest 中：

```text
file_start_time = 2024-01-06 09:52:31
```

可以作为：

```text
PROVISIONAL MANIFEST ANCHOR
```

但不能称为：

```text
VERIFIED SYNCHRONIZATION
```

即使它与 Electrical experiment coverage 非常吻合。

---

## Timezone

当前数据没有可靠 timezone 元数据。

因此：

```text
2024-01-06T09:52:31
```

保持 naive/local experiment datetime。

禁止擅自：

```text
append Z
assume UTC
assume Europe/London
assume Asia/Shanghai
```
