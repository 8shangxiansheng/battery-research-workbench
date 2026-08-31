# Current Time Baseline

## Experiment

```text
CELL_001 / EXP_001

start:
2024-01-06 09:52:31

end:
2024-01-06 20:58:54
```

## Electrical

Absolute records cover approximately the same experiment interval.

Known limitation:

```text
duplicate timestamps exist at some step/cycle boundaries
```

Therefore:

```text
timestamp != unique electrical row key
```

## Ultrasound U001

```text
frames = 3999
frame_index_raw = 0..3998

file_start_time =
2024-01-06 09:52:31

elapsed_min =
0.031217

elapsed_max =
39980.03

median interval =
10.0 s

sampling_rate_hz =
null
```

## Provisional interpretation

If manifest file_start_time denotes elapsed-time zero:

```text
t_abs_candidate = file_start_time + elapsed_time_s
```

Then approximately:

```text
first frame:
2024-01-06 09:52:31.031217

last frame:
2024-01-06 20:58:51.03
```

This is strong plausibility evidence only.

It is NOT validated synchronization.
