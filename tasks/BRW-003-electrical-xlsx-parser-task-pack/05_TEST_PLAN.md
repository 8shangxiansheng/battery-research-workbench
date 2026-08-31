# BRW-003 Test Plan

## T01 — Minimal workbook
Create a workbook with `record/cycle/step`.

Expected:
- parser succeeds
- canonical outputs populated

## T02 — Two cycles in one XLSX
Synthetic workbook:

```text
cycle 1: records 1..5
cycle 2: records 6..10
```

Expected:
- no manual file split
- `cycle_index_raw == {1,2}`

## T03 — Optional auxTemp / auxVol
Expected:
- if present → output parquet
- if absent → no fake output, manifest records absence

## T04 — Invalid required column
Delete `绝对时间` or another required core column.

Expected:
- explicit validation error
- message includes sheet + missing column

## T05 — Bad timestamp
Expected:
- explicit validation failure or recorded validation error
- never silently coerce to unrelated values

## T06 — Multi-XLSX experiment
Two assets under one Experiment.

Expected:
- both parsed
- rows retain distinct `electrical_asset_id`
- combined output sorted by timestamp

## T07 — Overlapping XLSX timestamps
Expected:
- overlap detected
- warning/error recorded
- no silent deduplication

## T08 — Parquet round trip
Write → read.

Expected:
- same row count
- same provenance
- same canonical timestamps/core numeric values

## T09 — Raw file immutability
SHA256 before/after.

Expected:
- identical

## T10 — Real-data golden values
Select beginning/middle/end + one sample from each observed Cycle.

Expected:
- parser output matches independently verified workbook values

## T11 — Current real CELL_001 integration
Expected:
- all manifest electrical assets parse
- actual cycle IDs visible
- row counts/timestamp ranges reported
- no unhandled exceptions
