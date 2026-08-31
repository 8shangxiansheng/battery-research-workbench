# BRW-008 Suggested Data Model

## ExperimentTimeReference

```text
battery_id
experiment_id
experiment_start_time
experiment_end_time
electrical_start_time
electrical_end_time
timezone_known
timezone_name
reference_sources
```

## TimeAnchorEvidence

```text
evidence_id
asset_id
source_type
source_ref
raw_value
parsed_value
message
```

## TimeAnchorCandidate

```text
anchor_id
asset_id
anchor_datetime
elapsed_time_s_at_anchor
source_type
source_ref
status
timezone_known
timezone_name
```

## AssetAnchorAssessment

```text
asset_id
elapsed_min_s
elapsed_max_s
candidates
selected_anchor_id
anchor_status
coverage
conflicts
validated_sync
```

## Important

```text
validated_sync = false
```

throughout BRW-008.
