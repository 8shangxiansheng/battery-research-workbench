# BRW-004 Test Plan

## T01 Perfect synthetic experiment
Expected: PASS.

## T02 Duplicate timestamp
Expected:
- rows preserved
- warning
- duplicate groups reported

## T03 Missing required column
Expected: FAIL.

## T04 Missing optional auxTemp
Expected:
- no crash
- unavailable explicit
- PASS_WITH_WARNINGS

## T05 Non-monotonic records
Expected: temporal anomaly.

## T06 Large gap
Inject 30 s gap.
Expected: warning.

## T07 Cycle mismatch
records contains cycle absent in cycles.parquet.
Expected: cross-table anomaly.

## T08 Step mismatch
Expected: step anomaly.

## T09 Physical outlier
Inject configurable impossible value.
Expected: warning, original value preserved.

## T10 Aux timestamp coverage
Expected: coverage metric.

## T11 JSON contract
Validate with Pydantic.

## T12 HTML
Required sections exist.

## T13 Figures
8 required artifacts exist/non-empty.

## T14 Real current dataset
Initial baseline:
- records=39996
- cycles=2
- steps=10
- duplicate timestamps=12
- timestamp 2024-01-06 09:52:31 → 20:58:54

If current data differs, report contract change rather than silently rewriting expected values.

## T15 Input immutability
SHA256 before/after.
Expected identical.
