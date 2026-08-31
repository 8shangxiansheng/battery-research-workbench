# BRW-009 — Timestamp Construction Engine

## Goal

Construct provenance-aware provisional absolute timestamps for elapsed-time ultrasound frames using BRW-008 selected time anchors.

## Inputs

- `time_anchors.json`
- `frames.parquet`

## Outputs

- `timestamped_ultrasound_frames.parquet`
- `timestamp_engine_manifest.json`
- JSON/HTML report

## Out of scope

Electrical matching, synchronization error, ambiguity handling, drift, cycle mapping, MeasurementEvent.
