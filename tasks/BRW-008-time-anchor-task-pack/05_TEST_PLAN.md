# BRW-008 Test Plan

## T01 Schema
Anchor datetime remains naive if input is naive.

## T02 Manifest anchor
file_start_time → MANIFEST_FILE_START / PROVISIONAL.

## T03 Coverage arithmetic
anchor + elapsed min/max.

## T04 Non-zero first elapsed
Do not equate anchor with first frame timestamp.

## T05 Missing anchor
Null remains null.

## T06 Manual override
Override wins deterministically.

## T07 Conflict
Conflicting evidence preserved.

## T08 Plausible but unverified
`validated_sync` must remain false.

## T09 Coverage mismatch
Warning only; no auto-shift.

## T10 Timezone guard
No Z/UTC invention.

## T11 Filename guard
Time-like filename token does not become selected anchor.

## T12 Multi asset
Independent anchors.

## T13 Elapsed reset
Multiple assets can each start near 0.

## T14 No cycle dependency
No cycle mapping needed.

## T15 Duplicate electrical timestamp guard
No unique-row lookup performed.

## T16 Immutability
Inputs unchanged.

## T17 Canonical JSON
Schema validates.

## T18 HTML report
Required sections exist.

## T19 Real CELL_001
U001 manifest anchor provisional and plausible.
