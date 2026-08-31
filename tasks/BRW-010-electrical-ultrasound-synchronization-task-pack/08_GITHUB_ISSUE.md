# BRW-010 — Electrical–Ultrasound Synchronization

## Goal

Synchronize BRW-009 ultrasound timestamps to BRW-003 electrical records by deterministic nearest-time matching while preserving ambiguity and boundary provenance.

## Deliverables

- aligned_ultrasound_frames.parquet
- synchronization_candidates.parquet
- synchronization_manifest.json
- sync report JSON/HTML
- 4 QA figures

## Red lines

No silent resolution of duplicate electrical timestamps.
No cycle-based synchronization.
No drift/interpolation.
