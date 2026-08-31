# Timestamp Semantics

## Provisional absolute timestamp

Means:

```text
absolute-looking datetime coordinate
derived deterministically from an accepted/provisional anchor
```

It does NOT mean:

```text
verified matching to electrical instrumentation clock
```

---

## Canonical source hierarchy

```text
BRW-008 selected anchor
    ↓
BRW-009 timestamp
```

Not:

```text
BRW-005 parser absolute_timestamp
    ↓
canonical timestamp
```

The parser field is compatibility evidence only.

---

## First frame

If:

```text
anchor elapsed = 0
first frame elapsed = 0.031217
```

then:

```text
first timestamp = anchor + 0.031217s
```

not anchor itself.
