# Condition Segments Manifest — V1.0

This optional manifest supports **explicit, operator-declared** time-varying
condition metadata. It is not populated from Cycle/Step transitions, filenames,
signal values, or inferred device settings. A separate assignment utility can
now produce an auditable event × condition-axis decision table. The deterministic
analysis API and live Report exploration panel expose descriptive SOC association
results for eligible assignments; this does not enable condition-stratified model
training or confirmatory inference.

File: `data/annotations/{battery_id}/{experiment_id}/condition_segments.csv`

This is a user-maintained sidecar declaration outside immutable `data/raw/`.
The referenced evidence file remains beneath `data/raw/` and is read-only.

```text
segment_id,battery_id,experiment_id,condition_axis_id,condition_value,unit,time_reference_asset_id,start_time,end_time,evidence_relative_path,evidence_sha256,declared_by,declared_at
```

## Field semantics

- `segment_id` is unique within `(battery_id, experiment_id)`.
- `condition_axis_id`, `condition_value`, and optional `unit` are labels declared
  by the study operator; the software does not assign physical meaning or
  validate that the declared condition was achieved.
- `time_reference_asset_id` identifies exactly one DataAsset within the same
  Battery/Experiment. The segment uses that asset's explicit absolute-time basis.
- `start_time`, `end_time`, and `declared_at` must be ISO-8601 timestamps with
  explicit UTC offsets. Naive datetimes are rejected. Intervals use the fixed
  half-open convention `[start_time, end_time)`; adjacent segments are allowed.
- Each interval must lie within the referenced DataAsset's timezone-aware
  `file_start_time` / `file_end_time`. Those bounds are still manifest claims;
  this check does not validate their device-clock accuracy.
- `evidence_relative_path` must resolve to a file beneath `data/raw/`, and
  `evidence_sha256` must match its current bytes. This proves file identity only,
  not scientific adequacy or reviewer identity.
- `declared_by` and `declared_at` record the operator declaration. Loader output
  is always marked `OPERATOR_DECLARED`; there is no automatic VERIFIED state.

Intervals may not overlap for the same
`(battery_id, experiment_id, time_reference_asset_id, condition_axis_id)`.
Uncovered time remains unclassified. Multiple axes may overlap because, for
example, temperature and rate are distinct study-defined dimensions.

## Current implementation boundary

`battery_workbench.conditions.load_condition_segments(...)` performs read-only
CSV, identity, timezone, DataAsset-bound, overlap, path-confinement, and checksum
validation. Each returned validation explicitly reports
`asset_window_status=WITHIN_DECLARED_ASSET_WINDOW`, while
`absolute_timebase_status=NOT_ASSESSED`, `synchronization_status=NOT_ASSESSED`,
and `measurement_event_assignment_status=NOT_IMPLEMENTED`. This distinction is
intentional: declared timestamp bounds are not anchor or sync verification. The
separate `assign_condition_segments_to_events(...)` utility accepts canonical
`CanonicalMeasurementEvent` records and matches only when the event's ultrasound DataAsset ID is exactly the segment's declared
time-reference asset. It uses half-open intervals, leaves gaps unclassified,
rejects naive event timestamps, flags conflicting overlapping input, and blocks
cross-asset clock transfer. Its output always keeps absolute-timebase and
synchronization status `NOT_ASSESSED`; it does not modify MeasurementEvents,
event eligibility, sync status, or downstream features. Assignment therefore
remains `OPERATOR_DECLARED`, not verified condition truth. The current Battery ×
`overall` / `charge` / `discharge` / `rest` correlation slices remain
electrochemical-phase slices, not condition slices. The live condition analysis
is returned separately and includes assignment coverage/status counts; it is not
part of frozen reports or persisted analysis artifacts. No real condition
manifest is currently available for CELL_001.
