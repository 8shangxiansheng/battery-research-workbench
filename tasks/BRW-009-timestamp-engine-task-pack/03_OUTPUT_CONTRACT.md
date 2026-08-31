# BRW-009 Output Contract

## Canonical processed outputs

```text
data/processed/synchronization/{battery_id}/{experiment_id}/
├── time_anchors.json
├── timestamped_ultrasound_frames.parquet
└── timestamp_engine_manifest.json
```

---

## Timestamped frame required columns

```text
battery_id
experiment_id
ultrasound_asset_id
source_file
source_line_index
frame_index_raw
waveform_group
waveform_row_index
elapsed_time_s

anchor_id
anchor_source_type
anchor_status
anchor_datetime
elapsed_time_s_at_anchor

clock_model_type
clock_scale
clock_offset_s
drift_enabled

provisional_absolute_timestamp
timestamp_available

timezone_known
timezone_name

legacy_parser_timestamp
legacy_timestamp_delta_s
legacy_timestamp_match
```

---

## Forbidden columns for BRW-009

不要新增：

```text
electrical_record_index
electrical_timestamp
sync_error_s
sync_ambiguous
candidate_record_count
cycle_index
step_index
voltage
current
temperature
SOC
SOH
```

这些属于 BRW-010/011。
