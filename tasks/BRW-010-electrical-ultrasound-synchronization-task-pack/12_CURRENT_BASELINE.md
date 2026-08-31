# Current BRW-010 Baseline

## Ultrasound

```text
CELL_001 / EXP_001 / U001

timestamped frames = 3999
frame_index_raw = 0..3998

first provisional timestamp ≈
2024-01-06 09:52:31.031217

last provisional timestamp ≈
2024-01-06 20:58:51.030000
```

Actual BRW-009 artifact is source of truth.

## Electrical

```text
records = 39996
coverage ≈
2024-01-06 09:52:31
→
2024-01-06 20:58:54
```

Known QA finding:

```text
12 duplicate record timestamps
9 duplicate timestamp groups
```

Mostly step/cycle boundaries.

Actual BRW-003 artifact must be rechecked.

## Important

Expected majority behavior:

```text
unique nearest match
```

But ambiguity count is UNKNOWN until real matching is executed.
