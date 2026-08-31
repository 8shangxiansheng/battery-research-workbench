# BRW-010 Output Contract

## `aligned_ultrasound_frames.parquet`

One row per ultrasound frame.

Required logical fields:

```text
battery_id
experiment_id

ultrasound_asset_id
frame_index_raw
waveform_group
waveform_row_index

provisional_absolute_timestamp

match_status

electrical_asset_id
electrical_record_locator
electrical_row_index
electrical_timestamp

sync_error_s
within_tolerance

candidate_timestamp_count
candidate_record_count
sync_ambiguous
ambiguity_type

boundary_flag

anchor_id
anchor_status
validated_sync
```

For ambiguous/out-of-tolerance frames,
selected electrical locator/timestamp may be null.

---

## `synchronization_candidates.parquet`

One row per nearest candidate electrical record.

Required logical fields:

```text
battery_id
experiment_id

ultrasound_asset_id
frame_index_raw
ultrasound_timestamp

electrical_asset_id
electrical_record_locator
electrical_row_index
electrical_timestamp

sync_error_s
within_tolerance

candidate_timestamp_rank
candidate_record_rank

electrical_timestamp_duplicate_count

boundary_flag
boundary_reason
```

---

## `synchronization_manifest.json`

Machine provenance + config + counts + checksums.

---

## Forbidden

Do not persist waveform samples.

Do not add full electrical feature enrichment here.
