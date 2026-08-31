# BRW-010 — Electrical–Ultrasound Synchronization

把整个任务包放到：

```text
battery-research-workbench/
└── tasks/
    └── BRW-010/
```

执行顺序：

```text
Inspect
→ Tests RED
→ Electrical timestamp index
→ Nearest-candidate matcher
→ Ambiguity handling
→ Boundary diagnostics
→ Persistence
→ Sync QA report
→ Current real-data validation
→ Final gate
```

---

## BRW-010 的唯一目标

把：

```text
BRW-009 timestamped_ultrasound_frames.parquet
+
BRW-003 electrical records.parquet
```

按时间进行确定性匹配，得到：

```text
ultrasound frame
↔
nearest electrical timestamp candidate(s)
```

并显式保存：

```text
sync_error_s
candidate_timestamp_count
candidate_record_count
sync_ambiguous
boundary_flag
match_status
```

---

## 关键原则

### 时间是主匹配键

禁止：

```text
Cycle 1 → 某个 TXT
Step → 某组 frame
SOC → 对齐键
```

同步只由：

```text
timestamp
```

驱动。

Cycle/Step 只能用于 boundary diagnostics，
不能参与选择“哪个 electrical record 更近”。

---

## 当前已知风险

Electrical 中已经确认：

```text
12 duplicate record timestamps
in 9 groups
```

主要出现在：

```text
step / cycle boundaries
```

因此：

```text
electrical timestamp
```

不能被当成唯一 row key。

---

## 默认歧义策略

如果最近时间点对应多个 electrical records：

```text
candidate_record_count > 1
sync_ambiguous = true
```

默认：

```text
selected electrical record = null
```

禁止静默选择 first/last row。

候选记录写入独立：

```text
synchronization_candidates.parquet
```

---

## BRW-010 不做

- drift correction
- waveform cross-correlation alignment
- interpolation
- cycle-based alignment
- SOC/SOH enrichment
- MeasurementEvent
- ML
- Agent/UI

真正科研事件表留给：

```text
BRW-011 MeasurementEvent
```
