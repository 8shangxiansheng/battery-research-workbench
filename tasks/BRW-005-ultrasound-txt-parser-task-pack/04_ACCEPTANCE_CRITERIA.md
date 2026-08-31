# BRW-005 Acceptance Criteria

## Raw integrity
- [ ] TXT immutable
- [ ] SHA256 before/after identical

## Manifest-driven
- [ ] DataAsset used
- [ ] multi-TXT Experiment supported
- [ ] filename not treated as identity

## Parser
- [ ] exactly validates semicolon sections
- [ ] frame ID preserved
- [ ] elapsed time preserved
- [ ] unknown fields preserved
- [ ] waveform values exact
- [ ] tail values preserved
- [ ] invalid line raises contextual error

## Provenance
- [ ] battery_id
- [ ] experiment_id
- [ ] ultrasound_asset_id
- [ ] source_file
- [ ] source_line_index

## Storage
- [ ] frames.parquet
- [ ] waveforms.zarr
- [ ] parser_manifest.json
- [ ] one Zarr group per asset
- [ ] no 1250-column waveform Parquet

## Current sample
- [ ] 3999 frames
- [ ] IDs 0..3998
- [ ] 1250 samples/frame
- [ ] 16 tail values/frame
- [ ] first elapsed 0.031217
- [ ] last elapsed ≈39980.03
- [ ] median frame interval ≈10s

## Scientific guard
- [ ] sampling_rate_hz remains null unless evidenced
- [ ] no TOF μs
- [ ] no frequency Hz/MHz
- [ ] no filtering/feature extraction

## Tests
- [ ] line parser
- [ ] wrong section count
- [ ] wrong waveform length
- [ ] wrong tail length
- [ ] invalid numeric token
- [ ] elapsed monotonicity
- [ ] raw frame ID preservation
- [ ] multi-TXT
- [ ] Zarr round trip
- [ ] Parquet round trip
- [ ] golden real values
- [ ] raw immutability
- [ ] current real-data integration
- [ ] pytest passes
- [ ] ruff passes
- [ ] format passes
- [ ] mypy passes
- [ ] git diff check passes

## Scope
- [ ] no BRW-006 QA implementation
- [ ] no ultrasound preprocessing
- [ ] no sync
- [ ] no ML
- [ ] no Agent/UI
