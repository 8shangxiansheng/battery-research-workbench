# BRW-010 Acceptance Criteria

## Inputs
- [ ] consumes BRW-009 timestamped frames
- [ ] consumes BRW-003 electrical records
- [ ] checks identity
- [ ] inputs unchanged

## Matching
- [ ] nearest-time matching
- [ ] previous/next candidate handling
- [ ] exact match
- [ ] tolerance
- [ ] tie tolerance
- [ ] no interpolation

## Duplicate timestamps
- [ ] duplicate row count
- [ ] duplicate group count
- [ ] duplicate timestamp produces ambiguity
- [ ] no silent first/last selection

## Ambiguity
- [ ] timestamp candidate count
- [ ] record candidate count
- [ ] ambiguity type
- [ ] ambiguous selected record = null
- [ ] candidates persisted

## Boundary
- [ ] duplicate boundary detection
- [ ] cycle/step transition diagnostic
- [ ] boundary does not alter matching

## Integrity
- [ ] one aligned row per ultrasound frame
- [ ] frame order unchanged
- [ ] electrical locators traceable
- [ ] no waveform duplication

## Multi asset
- [ ] multi ultrasound
- [ ] multi electrical
- [ ] asset identity preserved

## Time semantics
- [ ] no timezone guessing
- [ ] matching_performed=true
- [ ] validated_sync=false
- [ ] provisional anchor propagated

## Outputs
- [ ] aligned parquet
- [ ] candidate parquet
- [ ] manifest
- [ ] JSON report
- [ ] HTML report
- [ ] 4 figures

## Scope
- [ ] no drift
- [ ] no interpolation
- [ ] no cycle-based matching
- [ ] no MeasurementEvent

## Engineering
- [ ] pytest
- [ ] ruff
- [ ] format
- [ ] mypy as environment permits
- [ ] git diff
