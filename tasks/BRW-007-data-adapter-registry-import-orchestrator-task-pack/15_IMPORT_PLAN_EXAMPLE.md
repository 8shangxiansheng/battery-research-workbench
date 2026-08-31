# Example ExperimentImportPlan

```json
{
  "battery_id": "CELL_001",
  "experiment_id": "EXP_001",
  "asset_groups": {
    "electrical": ["E001"],
    "ultrasound": ["U001"]
  },
  "adapter_assignments": {
    "electrical": "ElectricalAdapter",
    "ultrasound": "UltrasoundAdapter"
  },
  "unsupported_modalities": [],
  "existing_outputs": {
    "electrical": true,
    "ultrasound": true
  }
}
```

Expected safe action with overwrite=false:

```text
electrical → SKIP_EXISTING
ultrasound → SKIP_EXISTING
```
