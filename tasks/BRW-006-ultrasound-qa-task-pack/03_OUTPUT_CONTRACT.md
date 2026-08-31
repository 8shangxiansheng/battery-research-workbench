# BRW-006 Output Contract

```text
data/artifacts/{battery_id}/{experiment_id}/ultrasound_qa/
├── ultrasound_qa_report.json
├── ultrasound_qa_report.html
├── figures/
│   ├── selected_raw_waveforms.png
│   ├── waveform_overlay.png
│   ├── waveform_heatmap.png
│   ├── rms_vs_elapsed_time.png
│   ├── p2p_vs_elapsed_time.png
│   ├── dc_offset_vs_elapsed_time.png
│   ├── frame_correlation_vs_elapsed_time.png
│   └── amplitude_distribution.png
└── tables/
    ├── frame_quality.csv
    ├── asset_summary.csv
    └── anomalies.csv
```

Canonical machine artifact：`ultrasound_qa_report.json`。

禁止生成 transformed waveform store。
