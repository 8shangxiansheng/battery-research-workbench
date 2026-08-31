# BRW-004 Acceptance Criteria

## Inputs
- [ ] 只读 BRW-003 processed outputs
- [ ] 不修改 input Parquet
- [ ] parser manifest provenance included

## Schema
- [ ] required columns
- [ ] dtype
- [ ] optional fields

## Completeness
- [ ] null count
- [ ] null ratio

## Temporal
- [ ] min/max
- [ ] duration
- [ ] monotonicity
- [ ] duplicate groups
- [ ] gap statistics

## Cycle
- [ ] per-cycle summary
- [ ] records/cycles consistency
- [ ] overlap check

## Step
- [ ] per-step summary
- [ ] records/steps consistency
- [ ] step order/time check

## Physical sanity
- [ ] voltage
- [ ] current
- [ ] capacity
- [ ] temperature
- [ ] SOC/DOD

## Cross-table
- [ ] records↔cycles
- [ ] records↔steps
- [ ] records↔auxTemp
- [ ] records↔auxVol

## Outputs
- [ ] JSON
- [ ] HTML
- [ ] anomalies.csv
- [ ] cycle_summary.csv
- [ ] step_summary.csv
- [ ] 8 figures

## Tests
- [ ] perfect synthetic
- [ ] duplicate timestamp
- [ ] missing required column
- [ ] missing optional aux
- [ ] non-monotonic time
- [ ] large gap
- [ ] cycle mismatch
- [ ] step mismatch
- [ ] physical outlier
- [ ] JSON contract
- [ ] HTML
- [ ] figures
- [ ] current real-data integration
- [ ] input immutability
- [ ] pytest passes
- [ ] changed-files ruff clean
- [ ] mypy passes

## Scope
- [ ] no parser redesign
- [ ] no ultrasound
- [ ] no sync
- [ ] no ML
- [ ] no Agent/UI
