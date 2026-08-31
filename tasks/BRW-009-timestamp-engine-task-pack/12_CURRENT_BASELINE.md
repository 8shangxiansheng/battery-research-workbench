# Current BRW-009 Baseline

## Experiment

```text
CELL_001 / EXP_001
```

## BRW-008 selected anchor

Expected current semantic state:

```text
asset = U001
source = MANIFEST_FILE_START
status = PROVISIONAL
anchor = 2024-01-06 09:52:31
elapsed_time_s_at_anchor = 0.0
timezone = UNKNOWN
validated_sync = false
```

Actual execution must read current `time_anchors.json`.

## U001 frames

```text
frames = 3999
frame_index_raw = 0..3998
elapsed_min = 0.031217
elapsed_max = 39980.03
```

Expected approximately:

```text
frame 0:
2024-01-06 09:52:31.031217

frame 3998:
2024-01-06 20:58:51.030000
```

Do not hard-code production values.
