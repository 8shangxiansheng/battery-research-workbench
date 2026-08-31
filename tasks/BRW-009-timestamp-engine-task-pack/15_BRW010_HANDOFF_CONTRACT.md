# What BRW-010 Will Consume

BRW-010 Synchronization should consume:

```text
timestamped_ultrasound_frames.parquet
+
electrical records.parquet
```

BRW-010 will add:

```text
electrical_record_index
electrical_timestamp
sync_error_s
candidate_record_count
sync_ambiguous
boundary_flag
```

BRW-009 must NOT add those fields.

This separation is intentional:

```text
BRW-008 = anchor
BRW-009 = timestamp construction
BRW-010 = cross-modal matching
```
