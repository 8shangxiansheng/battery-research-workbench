# BRW-011 — MeasurementEvent Canonical Multimodal Layer

## Goal

Build one canonical multimodal event per ultrasound frame using BRW-010 synchronization outputs and exact electrical locator enrichment.

## Outputs

- measurement_events.parquet
- measurement_event_candidates.parquet
- measurement_event_manifest.json
- JSON/HTML report

## Red lines

No rematching. No ambiguous candidate selection. No waveform duplication. No feature engineering.
