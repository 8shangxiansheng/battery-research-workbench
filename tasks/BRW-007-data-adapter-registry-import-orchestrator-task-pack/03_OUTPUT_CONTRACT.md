# BRW-007 Output Contract

BRW-007 不新增新的科学数据格式。

主要输出是 typed orchestration result：

```text
ExperimentImportPlan
ExperimentImportResult
ModalityImportResult
```

---

## Plan contract

至少：

```text
battery_id
experiment_id
asset_groups
adapter_assignments
expected_output_paths
unsupported_modalities
warnings
```

---

## Result contract

至少：

```text
battery_id
experiment_id
status
requested_modalities
imported_modalities
skipped_modalities
unsupported_modalities
source_asset_ids
modality_results
output_paths
warnings
errors
```

---

## Status

```text
SUCCESS
PARTIAL
FAILED
```
