# BRW-009 Functional Specification

## Purpose

把：

```text
selected time anchor
+
elapsed frame clock
```

转换成：

```text
provisional absolute frame timestamp
```

---

## Canonical formula

```text
t_abs = T_anchor + (elapsed - elapsed_at_anchor)
```

V1：

```text
ClockModel = OFFSET_ONLY
scale = 1.0
drift = false
```

---

## Source of truth

Anchor：

```text
BRW-008 time_anchors.json
```

Frame elapsed：

```text
BRW-005 frames.parquet
```

已有 parser `absolute_timestamp`
只作为 compatibility diagnostic。
