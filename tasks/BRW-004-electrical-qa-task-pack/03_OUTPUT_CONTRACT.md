# BRW-004 Output Contract

## Root

```text
data/artifacts/{battery_id}/{experiment_id}/electrical_qa/
```

## Required

```text
electrical_qa_report.json
electrical_qa_report.html

tables/cycle_summary.csv
tables/step_summary.csv
tables/anomalies.csv

figures/voltage_vs_time.png
figures/current_vs_time.png
figures/capacity_vs_time.png
figures/temperature_vs_time.png
figures/voltage_current_vs_time.png
figures/cycle_capacity.png
figures/step_timeline.png
figures/dqdv_vs_voltage.png
```

JSON 是 canonical machine-readable artifact。

HTML 只做人类阅读。
