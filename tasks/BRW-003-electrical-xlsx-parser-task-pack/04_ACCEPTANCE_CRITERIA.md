# Acceptance Criteria

BRW-003 is DONE only when all are checked.

## Raw integrity
- [ ] No source XLSX was modified
- [ ] SHA256 before/after matches

## Parser
- [ ] Manifest-driven asset discovery
- [ ] One XLSX can contain multiple cycles
- [ ] One experiment can contain multiple XLSX assets
- [ ] Required sheets/columns validated
- [ ] Optional sheets handled explicitly
- [ ] No silently skipped invalid row

## Provenance
- [ ] battery_id
- [ ] experiment_id
- [ ] electrical_asset_id
- [ ] source_file
- [ ] source_sheet
- [ ] source_row_index

## Electrical semantics
- [ ] Original raw cycle index preserved
- [ ] Original raw step index preserved
- [ ] Absolute timestamp parsed
- [ ] V / I / capacity core fields verified
- [ ] `SOC/DOD(%)` not mislabeled as SOC without evidence

## Outputs
- [ ] records.parquet
- [ ] cycles.parquet
- [ ] steps.parquet
- [ ] parser_manifest.json
- [ ] aux temperature/voltage if source exists

## Tests
- [ ] synthetic XLSX test
- [ ] 2-cycle synthetic test
- [ ] golden real-value test
- [ ] current real-data integration test
- [ ] parquet round-trip
- [ ] multi-XLSX experiment test
- [ ] overlap diagnostic test
- [ ] pytest passes
- [ ] ruff passes

## Scope discipline
- [ ] No ultrasound implementation
- [ ] No synchronization implementation
- [ ] No Agent implementation
- [ ] No ML implementation
