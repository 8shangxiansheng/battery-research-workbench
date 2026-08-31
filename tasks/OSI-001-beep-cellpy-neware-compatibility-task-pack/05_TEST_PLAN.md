# OSI-001 Test Plan

## T01 Package import
Import:
- cellpy
- beep

## T02 Version capture
Save Python/package versions.

## T03 Raw SHA256
Before == after.

## T04 BRW baseline
Confirm current canonical records/cycles/steps.

## T05 cellpy native Neware
Attempt real file.

## T06 cellpy custom XLSX
Attempt custom mapping or document why infeasible.

## T07 cellpy canonical bridge
If useful, feed temporary BRW-derived CSV.

## T08 BEEP Neware API discovery
Must use Neware implementation, not Maccor example.

## T09 BEEP direct real file
Attempt current XLSX.

## T10 BEEP bridge
Evaluate temporary canonical conversion if needed.

## T11 Golden comparison
Compare cycle capacities + representative records.

## T12 Plot smoke test
Generate at least one useful third-party plot if possible.

## T13 Main test regression
Run repository pytest.

## T14 No main dependency mutation
Check main pyproject/uv lock unchanged unless only unrelated pre-existing diff.
