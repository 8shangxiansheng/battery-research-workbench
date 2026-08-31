# BRW-005: Ultrasound TXT Parser

## Goal

Implement a manifest-driven parser for raw ultrasonic TXT DataAssets and persist:

```text
frames.parquet
waveforms.zarr
parser_manifest.json
```

with complete provenance and zero scientific transformation.

## Requirements

- Multi-TXT Experiment support
- Unknown metadata preservation
- Raw frame ID preservation
- Zarr waveform storage
- Golden real-value validation
- Raw SHA256 immutability
- No invented sampling frequency

## Out of Scope

Ultrasound QA, filtering, TOF, FFT, features, synchronization, ML, Agent, UI.
