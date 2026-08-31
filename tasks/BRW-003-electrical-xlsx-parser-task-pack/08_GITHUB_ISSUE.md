# BRW-003: Electrical XLSX Parser

## Goal

Implement a manifest-driven Electrical XLSX parser that converts immutable raw
battery cycling workbooks into canonical, provenance-preserving Parquet tables.

## Inputs

- `BatteryCell`
- `Experiment`
- one or more `DataAsset(modality="electrical")`
- raw `.xlsx`

## Outputs

- `records.parquet`
- `cycles.parquet`
- `steps.parquet`
- optional aux temperature/voltage
- `parser_manifest.json`

## Constraints

- Raw files immutable
- One XLSX may contain multiple cycles
- One Experiment may contain multiple XLSX files
- Cycle is not an alignment/file identity key
- Preserve raw cycle/step numbering
- Preserve source provenance
- Do not infer unknown semantics

## Acceptance

See:
- `tasks/BRW-003/04_ACCEPTANCE_CRITERIA.md`
- `tasks/BRW-003/05_TEST_PLAN.md`

## Out of scope

Ultrasound, multimodal sync, features, ML, Agent, UI.
