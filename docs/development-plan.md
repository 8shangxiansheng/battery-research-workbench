# Master Development Plan V1.1

## M0 — Foundation / Data Architecture
- BRW-001 Repository bootstrap
- BRW-002 Data Contracts
- BRW-002A Battery / Experiment / DataAsset manifests
- BRW-002B Registry layer
- BRW-002C Multi-file synchronization architecture

**Gate**
- Raw data uses Battery → Experiment → Modality directory structure.
- Manifest loaders pass tests.
- No component uses Cycle as primary file-alignment key.

## M1 — Data Engines
- BRW-003 Electrical XLSX Parser → standardized ElectricalExperiment / Parquet
- BRW-004 Electrical QA → read-only JSON / HTML / tables / figures（implemented）
- BRW-005 Ultrasound TXT Parser → UltrasoundFrame / Zarr
- BRW-006 Ultrasound Golden Validation
- BRW-007 Ultrasound QA Viewer

## M2 — Multimodal Synchronization
- BRW-008 Experiment Manifest + Time Anchor
- BRW-009 Ultrasound Absolute Timestamp Engine
- BRW-010 Nearest-Time Synchronizer + Sync QA
- BRW-011 MeasurementEvent + automatic Cycle/Step mapping
- BRW-011A Boundary flags
- BRW-011B Drift detection

**Gate**
- Match rate target > 99% on the current paired sample.
- Sync error is persisted for every match.
- First/middle/last frame manually validated.
- Multiple TXT assets within one Experiment are supported.

## M3 — Scientific Analysis
- Electrical Viewer
- Ultrasound Viewer
- Basic feature extraction
- Synthetic algorithm validation
- ConditionSlice
- Correlation analysis

## M4 — Reproducibility
- ResearchRun / provenance / Git commit / parameter tracking

## M5 — ML
- Electrical-only
- Ultrasound-only
- Multimodal
- Grouped by battery / leave-one-cell-out
- MLflow

## M6 — Agent
- Scientific Tool Registry
- LangGraph orchestrator
- Scientific hallucination tests
- Human approval for write/expensive tools

## M7 — UI
- JupyterLab workbench
