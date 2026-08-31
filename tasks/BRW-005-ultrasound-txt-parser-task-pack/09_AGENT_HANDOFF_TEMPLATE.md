# BRW-005 Agent Handoff Report

## Status
PASS / PARTIAL / FAIL

## Files changed

## Current ultrasound dataset

Battery:
Experiment:

| Asset | File | Frames | IDs | Elapsed range | Samples/frame | Tail length |
|---|---|---:|---|---|---:|---:|
| | | | | | | |

## Output storage

frames.parquet:
waveforms.zarr:
parser_manifest.json:

## Zarr

| Asset | Shape | Dtype | Min | Max |
|---|---|---|---:|---:|
| | | | | |

## Golden checks

| Asset | Frame | Sample index | Raw TXT | Parsed/Zarr | Match |
|---|---:|---:|---:|---:|---|
| | | | | | |

## Raw integrity

SHA256 before:
SHA256 after:
Match:

## Time metadata

file_start_time:
absolute_timestamp available:
sampling_rate_hz:

## Tests

pytest:
coverage:
ruff:
format:
mypy:
git diff:

## Missing physical metadata

- sampling rate:
- transducer center frequency:
- gain:
- probe/coupling metadata:

## Known limitations

- BRW-006 QA not implemented
- no filtering
- no TOF
- no frequency feature
- no synchronization
- no ML
- no Agent/UI
