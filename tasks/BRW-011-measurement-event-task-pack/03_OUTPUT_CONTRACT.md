# BRW-011 Output Contract

## Root

```text
data/processed/multimodal/{battery_id}/{experiment_id}/
```

Required:

```text
measurement_events.parquet
measurement_event_candidates.parquet
measurement_event_manifest.json
```

## MeasurementEvent logical fields

```text
measurement_event_id
battery_id
experiment_id
ultrasound_asset_id
frame_index_raw
event_order_index
waveform_group
waveform_row_index
provisional_absolute_timestamp
elapsed_time_s
match_status
sync_error_s
within_tolerance
candidate_timestamp_count
candidate_record_count
sync_ambiguous
ambiguity_type
boundary_flag
matching_performed
validated_sync
sync_semantics
anchor_id
anchor_status
electrical_asset_id
electrical_record_locator
electrical_row_index
electrical_timestamp
cycle_index_raw
step_index_raw
step_type
voltage_v
current_a
capacity_ah
charge_capacity_ah
discharge_capacity_ah
energy_wh
power_w
temperature_c
soc_dod_percent
contact_resistance_mohm
dq_dv_raw
event_quality_status
analysis_eligible
event_quality_reason
```

Actual field availability follows BRW-003 canonical schema.
