# BRW-011 Handoff Contract

BRW-011 MeasurementEvent should consume:

```text
aligned_ultrasound_frames.parquet
synchronization_candidates.parquet
electrical records.parquet
waveforms.zarr locators
```

Then enrich selected unique matches with:

```text
cycle
step
voltage
current
capacity
temperature
...
```

For ambiguous sync rows BRW-011 must retain:

```text
sync_ambiguous
candidate_record_count
boundary_flag
```

and must not pretend the electrical state is uniquely known.
