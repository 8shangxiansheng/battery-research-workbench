# BRW-006 Master Vibe Coding Prompt

你正在维护 `battery-research-workbench` V1.1。BRW-003/004/005 已完成。

## 0. 先读，不要改代码

按顺序读取：
1. `AGENTS.md`
2. `README.md`
3. `docs/development-plan.md`
4. `docs/tech-stack.md`
5. `docs/data_contract/ultrasound_txt.md`
6. `tasks/BRW-005/03_OUTPUT_CONTRACT.md`
7. `tasks/BRW-005/12_CURRENT_BASELINE.md`
8. 当前 `src/battery_workbench/ultrasound/`、`storage/`、`tests/`
9. 当前真实 `frames.parquet`、`waveforms.zarr`、`parser_manifest.json`

第一轮只 Inspect。

# 1. Task

实现 **BRW-006 — Deterministic Ultrasound QA Engine**。

正式输入只允许 BRW-005 processed outputs，不把 raw TXT 当主流程输入。

# 2. 当前基线

```text
CELL_001 / EXP_001 / U001
frames = 3999
frame_index_raw = 0..3998
shape = (3999, 1250)
dtype = int32
global min = -29123
global max = 29392
elapsed = 0.031217 .. 39980.03 s
median interval = 10.0 s
sampling_rate_hz = null
```

必须先核对当前仓库实际值。

# 3. Structural QA

检查：
- required metadata columns
- frame count vs Zarr rows
- waveform sample count vs Zarr columns
- dtype vs manifest
- one valid group per asset
- waveform locator valid
- metadata/Zarr asset consistency

# 4. Provenance QA

每帧必须可追溯：
`battery_id, experiment_id, ultrasound_asset_id, source_file, source_line_index, frame_index_raw, waveform_group, waveform_row_index`。

检查 null / duplicate locator / out-of-range locator / asset mismatch。

# 5. Temporal QA

基于 `elapsed_time_s`：
`min/max/duration/monotonicity/duplicate elapsed/median-min-max interval/large gap/non-positive interval`。

如果 `absolute_timestamp` 存在，只检查机械一致性，不做 Electrical matching。

# 6. Frame-level waveform QA

每帧计算 QA-only diagnostics：

```text
waveform_min
waveform_max
waveform_mean
waveform_std
waveform_rms
waveform_p2p
zero_sample_fraction
all_zero_frame_flag
constant_frame_flag
nan_or_nonfinite_flag
```

输出 `tables/frame_quality.csv`。

# 7. Saturation/clipping 规则

当前没有 ADC rails，因此禁止断言 confirmed clipping。

只有配置 `adc_min/adc_max` 时才能做 rail-hit 判断。否则仅允许：
`repeated_global_min_count / repeated_global_max_count / extreme_plateau_fraction / POSSIBLE_SATURATION`。

# 8. DC / RMS / P2P QA

计算每帧 mean/DC、RMS、P2P；用 configurable robust rule（推荐 MAD）发现 outlier/jump。阈值必须在 `configs/ultrasound_qa.yaml`。

不得修改波形。

# 9. Cross-frame QA

对相邻帧计算 Pearson waveform correlation，只用于形态突变诊断。

禁止做 waveform shift / cross-correlation alignment / TOF shift。

至少检查：
`adjacent_frame_correlation, delta_rms, delta_p2p, delta_mean`。

# 10. Anomaly model

结构：

```json
{
  "code": "RMS_OUTLIER",
  "severity": "warning",
  "scope": "frame",
  "asset_id": "U001",
  "frame_index_raw": 123,
  "message": "...",
  "metrics": {}
}
```

推荐 codes：
`METADATA_ZARR_MISMATCH, MISSING_WAVEFORM_GROUP, INVALID_WAVEFORM_LOCATOR, NON_MONOTONIC_ELAPSED_TIME, LARGE_FRAME_GAP, ALL_ZERO_FRAME, CONSTANT_FRAME, POSSIBLE_SATURATION, RMS_OUTLIER, P2P_OUTLIER, DC_OFFSET_OUTLIER, FRAME_RMS_JUMP, FRAME_P2P_JUMP, FRAME_DC_JUMP, LOW_ADJACENT_CORRELATION`。

# 11. Status

FAIL：结构损坏、Zarr 缺失/不一致、无法访问波形、严重数据损坏超过可配置阈值。

PASS_WITH_WARNINGS：少量 outlier、低相关、possible saturation、large gap、未知可选 metadata。

PASS：无 critical 且无重要 warnings。

`sampling_rate_hz=null` 不能导致 FAIL。

# 12. Required figures

至少 8 张：

```text
selected_raw_waveforms.png
waveform_overlay.png
waveform_heatmap.png
rms_vs_elapsed_time.png
p2p_vs_elapsed_time.png
dc_offset_vs_elapsed_time.png
frame_correlation_vs_elapsed_time.png
amplitude_distribution.png
```

规则：
- 横轴是 sample index，不是 μs
- amplitude 单位未知时写 Raw amplitude / arbitrary ADC units，不写 V/Pa
- overlay 只抽样 20–50 帧
- heatmap 可显示 downsample，但只影响显示，不影响 QA 数值

# 13. JSON contract

输出 `ultrasound_qa_report.json`：

```json
{
  "battery_id":"...",
  "experiment_id":"...",
  "qa_version":"0.1.0",
  "inputs":{},
  "summary":{},
  "schema":{},
  "provenance":{},
  "temporal":{},
  "waveform":{},
  "cross_frame":{},
  "assets":[],
  "anomalies":[],
  "warnings":[],
  "scientific_metadata":{"sampling_rate_hz":null},
  "status":"PASS|PASS_WITH_WARNINGS|FAIL",
  "artifacts":{}
}
```

# 14. Required HTML sections

1 Experiment Overview
2 Input/Provenance
3 QA Status
4 Structural Integrity
5 Temporal Quality
6 Waveform Amplitude Statistics
7 Frame-level Quality
8 Cross-frame Stability
9 Anomalies/Warnings
10 Figures
11 QA Configuration
12 Scientific Metadata Limitations
13 Software/Version Provenance

# 15. Required tables

`frame_quality.csv` 至少包含：

```text
battery_id, experiment_id, ultrasound_asset_id, frame_index_raw, elapsed_time_s,
waveform_min, waveform_max, waveform_mean, waveform_std, waveform_rms, waveform_p2p,
zero_sample_fraction, all_zero_frame_flag, constant_frame_flag,
adjacent_frame_correlation, delta_rms, delta_p2p, delta_mean, qa_flag_count
```

另输出 `asset_summary.csv` 和 `anomalies.csv`。

# 16. Recommended code structure

```text
src/battery_workbench/ultrasound/qa/
├── __init__.py
├── schemas.py
├── structural.py
├── temporal.py
├── waveform.py
├── cross_frame.py
├── anomalies.py
├── figures.py
├── report.py
└── service.py
```

统一 public API：`run_ultrasound_qa(...)`。

# 17. Config

新增 `configs/ultrasound_qa.yaml`，阈值不得散落代码。

# 18. Tests FIRST

必须覆盖：
1. perfect synthetic → PASS
2. metadata/Zarr mismatch → FAIL
3. missing Zarr group → FAIL
4. all-zero frame
5. constant non-zero frame
6. DC outlier
7. RMS outlier
8. P2P outlier
9. low adjacent correlation
10. large gap
11. non-monotonic elapsed
12. possible saturation without known rails
13. known ADC rails synthetic
14. JSON contract
15. HTML sections
16. 8 figures
17. input immutability
18. current real-data integration

# 19. Scientific guard

当前 `sampling_rate_hz = null`，因此禁止输出：
`TOF μs / frequency Hz / frequency MHz / spectral centroid Hz / physical band energy`。

BRW-006 不做 FFT，避免任务边界膨胀。

# 20. Input immutability

不得修改 `frames.parquet / waveforms.zarr / parser_manifest.json`。

至少验证：
- Parquet SHA256 before/after
- Zarr shape/dtype/content checksum before/after

# 21. Before finishing

运行：

```bash
pytest
ruff check <本次修改文件>
ruff format --check <本次修改文件>
mypy src
git diff --check
```

真实运行 `CELL_001 / EXP_001` 并生成所有 artifacts。

# 22. Final handoff

必须报告：Status、Files changed、Structural QA、Temporal QA、Waveform QA、Cross-frame QA、Anomalies、Final QA status、Artifacts、Tests、Input integrity、Scientific metadata limitations、Known limitations。

Known limitations 必须明确：未做 preprocessing / TOF / physical FFT features / synchronization / ML / Agent / UI。
