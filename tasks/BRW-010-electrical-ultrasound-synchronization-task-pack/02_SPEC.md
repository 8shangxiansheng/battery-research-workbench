# BRW-010 Functional Specification

## Purpose

建立：

```text
provisional ultrasound timestamp
→ nearest electrical timestamp candidate(s)
```

的确定性、可审计同步层。

---

## Matching key

唯一 primary alignment dimension：

```text
time
```

Cycle/Step 不是 alignment key。

---

## Default ambiguity policy

```text
1 candidate record
→ select

>1 candidate records
→ ambiguous
→ selected record = null
```

---

## Core outputs

```text
aligned_ultrasound_frames.parquet
synchronization_candidates.parquet
synchronization_manifest.json
```
