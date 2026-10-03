# Synchronization Engine

For each ultrasound `DataAsset`, construct a provisional absolute timestamp
from its explicitly referenced time-anchor evidence and that asset's own
`elapsed_time_s`:

```text
ultrasound frame absolute time
= ultrasound asset anchor time
  + (frame elapsed_time_s - elapsed_time_s_at_anchor)
```

The current nearest-record matcher compares that timestamp with records in the
same Battery/Experiment. It assigns an electrical identity only when exactly
one record is nearest and within tolerance. Duplicate/equidistant candidates,
conflicting or missing anchors, incompatible clocks, and out-of-coverage
frames remain unresolved; they are never disambiguated by Cycle, Step,
filename, row order, or an inferred start-time offset.

Persist the absolute `sync_error_s` for every candidate and the signed delta
(`electrical timestamp - ultrasound timestamp`) where its direction is defined.
Preserve DataAsset IDs, source-file paths/hashes, and raw row/frame locators so
each match or unresolved candidate can be independently audited. A provisional
match is not a validated clock synchronization.
