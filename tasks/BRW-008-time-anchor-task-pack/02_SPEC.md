# BRW-008 Functional Specification

## Purpose

建立可审计的：

```text
elapsed-time asset
→ time anchor candidate
→ provenance
→ provisional coverage
```

而不是做同步匹配。

---

## Core distinction

```text
Anchor
≠
Timestamp Engine
≠
Synchronization
```

BRW-008:
anchor.

BRW-009:
per-frame timestamp construction.

BRW-010:
frame ↔ electrical matching.

---

## Canonical rule

如果：

```text
asset.file_start_time
```

存在：

它可以成为：

```text
PROVISIONAL manifest anchor
```

但不是 validated synchronization。

---

## Timezone

Timezone 缺失必须显式保留为 unknown。
