# Production Integration Options After OSI-001

## Option A

```text
Neware XLSX
↓
BRW Custom Parser
↓
BRW Canonical
↓
cellpy Adapter
↓
cellpy analysis
```

## Option B

```text
Neware
↓
cellpy
↓
BRW Canonical Adapter
```

Only if direct compatibility and provenance are strong.

## Option C

```text
BRW Canonical
↓
BEEP Adapter
↓
BEEP structuring / features
```

## Option D — Hybrid

Recommended candidate:

```text
Raw ingestion:
BRW

Battery analysis:
cellpy

Feature / ML utilities:
BEEP

Identity / provenance:
BRW
```

## Option E

No integration.

Use if compatibility cost exceeds benefit.
