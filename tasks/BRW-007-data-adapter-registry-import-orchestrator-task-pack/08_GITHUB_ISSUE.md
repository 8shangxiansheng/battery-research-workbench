# BRW-007 — Data Adapter Registry & Experiment Import Orchestrator

## Goal

Create a unified adapter and orchestration layer over existing modality parsers.

## Key deliverables

- DataAdapter abstraction
- DataAdapterRegistry
- ElectricalAdapter
- UltrasoundAdapter
- ExperimentImportPlan
- ExperimentImportResult
- real ExperimentImporter
- dry-run support
- safe existing-output policy

## Out of scope

Parser rewrites, QA rewrites, synchronization, ML, Agent, UI.
