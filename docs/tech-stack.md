# Technology Stack — V1.1

The technology choices are unchanged; V1.1 changes the domain/data architecture.

| Technology | Role |
|---|---|
| Python + Pydantic | Battery / Experiment / DataAsset / MeasurementEvent domain models |
| pandas + openpyxl | XLSX electrical ingestion |
| NumPy + SciPy | deterministic ultrasonic signal processing |
| PyArrow / Parquet | electrical records + MeasurementEvent tables |
| Zarr | frame × sample ultrasound waveform arrays |
| SQLAlchemy | metadata/provenance persistence boundary |
| SQLite | local development metadata DB |
| PostgreSQL | multi-project/production metadata DB |
| FastAPI | stable application API for UI/Agent/Notebook |
| pytest | golden, synthetic, integration and agent behavior tests |
| LangGraph | P9 Research Agent orchestration |
| MLflow | P8 model/research experiment tracking |
| Kedro | optional deterministic pipeline orchestration when complexity justifies it |
| JupyterLab Extension | primary P10 scientific workbench UI |
| PaperQA2 | optional literature tool, outside raw-data processing path |

## V1.1 architecture rule

The physical raw-data hierarchy is:

```text
Battery → Experiment → DataAsset
```

The scientific alignment hierarchy is:

```text
DataAsset → Record/Frame → timestamp → MeasurementEvent → Cycle/Step/SOC/SOH
```

This prevents the software from assuming one file equals one cycle.
