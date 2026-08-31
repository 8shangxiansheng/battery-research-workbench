# BRW-010 Test Plan

## T01 Exact unique match
Unique, error 0.

## T02 Nearest previous

## T03 Nearest next

## T04 Equidistant tie
Ambiguous, selected null.

## T05 Duplicate timestamp rows
Ambiguous, selected null.

## T06 Duplicate + equidistant
Correct ambiguity type.

## T07 Tolerance boundary
`error == max_sync_error_s` is within tolerance.

## T08 Out of tolerance
Candidate kept, selected null.

## T09 Empty electrical input
Explicit failure/no-candidate policy.

## T10 Ultrasound timestamp unavailable
Not matched.

## T11 Preserve ultrasound row count/order

## T12 Non-monotonic electrical timestamps
Sorted lookup only; locator preserved.

## T13 Duplicate ultrasound timestamp
Frames not deduplicated.

## T14 Timezone mismatch
No implicit conversion.

## T15 Naive-naive
Allowed, timezone unknown.

## T16 Duplicate timestamp boundary
Boundary true.

## T17 Cycle/step transition boundary
Diagnostic only.

## T18 Cycle labels do not change time matching

## T19 Candidate table completeness

## T20 Ambiguous selected record null

## T21 Sync error arithmetic

## T22 Multi-ultrasound asset

## T23 Multi-electrical asset

## T24 No waveform duplication

## T25 Input immutability

## T26 Manifest/report schema

## T27 Four figures generated

## T28 Real CELL_001 integration

## T29 Golden frame candidate audit
0/1000/2000/3000/3998.
