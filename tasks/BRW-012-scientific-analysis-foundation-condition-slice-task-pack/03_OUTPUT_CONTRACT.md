# BRW-012 Output Contract

```text
data/processed/analysis_slices/{battery_id}/{experiment_id}/{analysis_slice_id}/
├── analysis_slice.parquet
└── analysis_slice_manifest.json
```

```text
data/artifacts/{battery_id}/{experiment_id}/analysis_slices/{analysis_slice_id}/
├── analysis_slice_report.json
└── analysis_slice_report.html
```

必须保留：

```text
measurement_event_id
waveform_group
waveform_row_index
```

禁止 waveform arrays 和 derived ultrasound features。
