# Database ER — V1.1

```mermaid
erDiagram
    BATTERY_CELL ||--o{ EXPERIMENT : has
    EXPERIMENT ||--o{ DATA_ASSET : owns
    EXPERIMENT ||--o{ MEASUREMENT_EVENT : contains

    DATA_ASSET ||--o{ ULTRASOUND_FRAME : source_of
    DATA_ASSET ||--o{ ELECTRICAL_WINDOW : source_of

    ULTRASOUND_FRAME ||--o| MEASUREMENT_EVENT : anchors
    ELECTRICAL_WINDOW ||--o| MEASUREMENT_EVENT : matches

    MEASUREMENT_EVENT ||--o{ FEATURE_VALUE : produces
    FEATURE_DEFINITION ||--o{ FEATURE_VALUE : defines

    DATASET_SLICE ||--o{ RESEARCH_RUN : input_to
    RESEARCH_RUN ||--o{ TOOL_CALL : records
    RESEARCH_RUN ||--o{ RUN_ARTIFACT : produces
```

The provenance chain for every analyzed point must be recoverable:

```text
Battery
→ Experiment
→ Ultrasound DataAsset + frame index
→ Electrical DataAsset + record index
→ MeasurementEvent
→ feature/model/result
```
