# BRW-009 Test Plan

## T01 Basic timestamp arithmetic
Microsecond exactness.

## T02 Non-zero elapsed-at-anchor
Correct relative conversion.

## T03 First elapsed non-zero
Anchor != first frame timestamp.

## T04 Missing anchor
Null timestamp + warning.

## T05 Rejected anchor
No timestamp.

## T06 Conflicting selected anchor
Timestamp allowed with propagated warning.

## T07 Naive timezone
Remains naive.

## T08 Aware timezone synthetic
Preserved, not converted.

## T09 Multi-asset
Different anchors.

## T10 Elapsed reset
Independent clocks.

## T11 Preserve order/count
No sorting/dropping.

## T12 Duplicate elapsed
No epsilon/dedupe.

## T13 Non-monotonic elapsed
No correction.

## T14 Missing anchor assessment
Explicit diagnostic.

## T15 Orphan anchor state
Explicit diagnostic.

## T16 Legacy timestamp match
Diagnostic pass.

## T17 Legacy timestamp mismatch
Warning only.

## T18 Parquet round-trip
Timestamp precision stable.

## T19 Input checksums
Before/after identical.

## T20 No electrical dependency
Core engine fixture has no electrical data.

## T21 No drift
scale=1.0, drift=false.

## T22 Report schema
Pydantic validate.

## T23 Current real integration
CELL_001 / EXP_001 / U001.

## T24 Golden frames
0,1000,2000,3000,3998 independently verified.
