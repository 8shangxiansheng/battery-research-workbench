# BRW-008 Output Contract

## Canonical state

```text
data/processed/synchronization/{battery_id}/{experiment_id}/time_anchors.json
```

最低结构：

```json
{
  "battery_id": "CELL_001",
  "experiment_id": "EXP_001",
  "anchor_version": "0.1.0",
  "experiment_reference": {},
  "assets": [],
  "warnings": [],
  "limitations": [],
  "validated_sync": false
}
```

---

## Per asset

至少：

```text
asset_id
modality
elapsed_min_s
elapsed_max_s

candidates
selected_anchor_id
anchor_status

coverage
conflicts

validated_sync
```

---

## Report

```text
data/artifacts/{battery_id}/{experiment_id}/time_anchor/
├── time_anchor_report.json
└── time_anchor_report.html
```

---

## Forbidden outputs

BRW-008 不生成：

```text
synchronized_frames.parquet
measurement_events.parquet
frame_record_mapping.parquet
```
