# BRW-009 Acceptance Criteria

## Inputs
- [ ] reads `time_anchors.json`
- [ ] reads `frames.parquet`
- [ ] does not require electrical records
- [ ] inputs remain unchanged

## Clock
- [ ] OFFSET_ONLY
- [ ] scale=1.0
- [ ] no drift
- [ ] non-zero elapsed-at-anchor supported

## Timestamp
- [ ] microsecond precision
- [ ] first frame not confused with anchor
- [ ] per-frame timestamp construction
- [ ] missing anchor → null
- [ ] rejected anchor → no timestamp

## Provenance
- [ ] anchor id
- [ ] anchor source
- [ ] anchor status
- [ ] clock model
- [ ] timezone metadata

## Multi-asset
- [ ] separate clock per asset
- [ ] elapsed resets supported
- [ ] no cross-asset concatenation assumption

## Integrity
- [ ] row count preserved
- [ ] row order preserved
- [ ] frame ids preserved
- [ ] no sorting
- [ ] no deduplication

## Legacy compatibility
- [ ] parser absolute timestamp only diagnostic
- [ ] canonical timestamp always anchor-derived
- [ ] mismatch cannot overwrite canonical value

## Outputs
- [ ] timestamped_ultrasound_frames.parquet
- [ ] timestamp_engine_manifest.json
- [ ] report JSON/HTML

## Current baseline
- [ ] U001 = 3999 rows
- [ ] frame 0 timestamp verified independently
- [ ] frame 3998 timestamp verified independently
- [ ] validated_sync=false

## Scope
- [ ] no electrical matching
- [ ] no sync error
- [ ] no cycle mapping
- [ ] no drift fit
- [ ] no MeasurementEvent
