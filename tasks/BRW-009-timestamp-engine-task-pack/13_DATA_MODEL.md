# BRW-009 Suggested Data Model

## ClockModel

```text
model_type
anchor_id
anchor_datetime
elapsed_time_s_at_anchor
scale
offset_s
drift_enabled
```

V1 invariant:

```text
model_type = OFFSET_ONLY
scale = 1.0
offset_s = 0.0
drift_enabled = false
```

## TimestampEngineAssetResult

```text
asset_id
frame_count
timestamp_available_count
timestamp_missing_count
elapsed_min/max
timestamp_min/max
anchor_id
anchor_status
clock_model
legacy comparison
diagnostics
```

## TimestampEngineReport

```text
battery_id
experiment_id
engine_version
input/output row counts
assets
warnings
errors
status
validated_sync=false
```
