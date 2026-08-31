# BRW-011 Functional Specification

## Purpose

建立统一 `MeasurementEvent`，作为后续科研分析 canonical multimodal row model。

## Grain

```text
1 event = 1 ultrasound frame
```

## Unique match

```text
ultrasound frame + selected electrical locator → exact electrical state enrichment
```

## Ambiguous match

```text
event preserved
electrical state = null
candidate evidence retained
```

## Red line

BRW-011 does not perform time matching.
