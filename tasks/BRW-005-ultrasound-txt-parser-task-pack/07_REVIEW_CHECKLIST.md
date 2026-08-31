# Human Review Checklist

BRW-005 完成后人工检查：

## Files
- [ ] frames.parquet exists
- [ ] waveforms.zarr exists
- [ ] parser_manifest.json exists

## Current sample
- [ ] 3999 frames
- [ ] raw IDs 0..3998
- [ ] 1250 samples each
- [ ] first elapsed 0.031217
- [ ] last elapsed ≈39980.03
- [ ] median frame interval ≈10s

## Raw waveform
随机打开至少 5 帧：
- [ ] frame 0
- [ ] frame 1000
- [ ] frame 2000
- [ ] frame 3000
- [ ] frame 3998

对比 TXT：
- [ ] sample 0
- [ ] sample 10
- [ ] sample 1249

必须逐值一致。

## Provenance
- [ ] battery
- [ ] experiment
- [ ] asset ID
- [ ] source file
- [ ] source line
- [ ] frame raw ID

## Scientific guard
- [ ] sampling_rate_hz not invented
- [ ] no TOF μs
- [ ] no frequency MHz
- [ ] no filtering
- [ ] no normalization

## Integrity
- [ ] TXT SHA256 unchanged

## Scope
- [ ] no BRW-006
- [ ] no sync
- [ ] no ML
- [ ] no Agent/UI
