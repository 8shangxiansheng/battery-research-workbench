# BRW-007 Architecture Guide

## Before

```text
Caller
├── calls electrical parser directly
└── calls ultrasound parser directly
```

## After

```text
Caller
↓
ExperimentImporter
↓
AdapterRegistry
├── ElectricalAdapter
└── UltrasoundAdapter
↓
Existing parser services
```

## Future

```text
CLI
FastAPI
JupyterLab
Agent Tool Registry
```

all depend on:

```text
Experiment Import Service
```

not individual parser internals.
