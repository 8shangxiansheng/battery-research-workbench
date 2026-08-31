# BRW-005 Master Vibe Coding Prompt

你正在维护 `battery-research-workbench`，当前架构版本 V1.1。

已完成：

```text
BRW-003 Electrical XLSX Parser ✅
BRW-004 Electrical QA ✅
```

现在执行：

> **BRW-005 — Ultrasound TXT Parser**

---

# 0. 开始前先读，不要直接改代码

必须按顺序阅读：

1. `AGENTS.md`
2. `README.md`
3. `docs/development-plan.md`
4. `docs/tech-stack.md`
5. `docs/data_contract/ultrasound_txt.md`
6. `docs/data_contract/manifests.md`
7. `docs/architecture/multi-experiment-synchronization.md`
8. `tasks/BRW-003/` 中的 parser / provenance 设计（若存在）
9. 当前：
   - `src/battery_workbench/domain/`
   - `src/battery_workbench/io/ultrasound/`
   - `src/battery_workbench/io/experiment/`
   - `src/battery_workbench/storage/`
   - `tests/`
10. `data/raw/manifests/data_assets.csv`
11. 当前仓库中所有 `modality == ultrasound` 的 DataAsset
12. 当前真实 TXT 文件

第一轮只做 Inspect，不修改代码。

---

# 1. Task

实现：

> **Manifest-driven Ultrasound TXT Parser**

目标是将一个 Experiment 下的一个或多个 Ultrasound TXT DataAsset
可靠解析成：

```text
frames.parquet
waveforms.zarr
parser_manifest.json
```

并保持完整 provenance。

BRW-005 不负责科学信号处理。

---

# 2. Architecture constraints

必须遵循：

```text
Battery
  ↓
Experiment
  ↓
Ultrasound DataAsset(s)
  ↓
TXT Parser
  ↓
Frame Metadata + Raw Waveform
  ↓
Parquet + Zarr
```

一个 Experiment 可以有：

```text
1..N Ultrasound TXT DataAssets
```

每个 TXT：

- 可以有不同 frame 数
- 后续可能有不同 waveform sample count
- elapsed time 可以从 0 重新开始
- 必须独立保留 file_start_time / elapsed_time

不要假设：

```text
一个 TXT = 一个 Cycle
```

也不要在 BRW-005 映射 Cycle。

Cycle mapping 属于后面的 Synchronization Engine。

---

# 3. Current confirmed TXT contract

当前样例每一条非空行：

```text
field_0 ;
field_1 ;
elapsed_time ;
field_3a field_3b ;
1250 waveform integer samples ;
16 trailing values
```

当前安全 canonical 名称：

```text
frame_index_raw
unknown_field_1
elapsed_time_s
unknown_meta_0
unknown_meta_1
waveform
unknown_tail
```

不要把 unknown 字段擅自解释成：

- gain
- trigger
- temperature
- voltage
- channel
- timestamp
- sampling frequency

除非后续设备文档明确证实。

---

# 4. Required output

每个 Experiment：

```text
data/processed/ultrasound/
└── {battery_id}/
    └── {experiment_id}/
        ├── frames.parquet
        ├── waveforms.zarr/
        │   ├── {ultrasound_asset_id}/
        │   │   └── waveform
        │   └── ...
        └── parser_manifest.json
```

---

# 5. frames.parquet canonical schema

至少：

```text
battery_id                 string
experiment_id              string
ultrasound_asset_id        string

source_file                string
source_line_index          int

frame_index_raw            int
elapsed_time_s             float

unknown_field_1            string | nullable
unknown_meta_0             string | nullable
unknown_meta_1             string | nullable

unknown_tail               list/string-json | nullable

waveform_store_uri         string
waveform_group             string
waveform_row_index         int

waveform_sample_count      int

file_start_time            datetime | null
absolute_timestamp         datetime | null
```

注意：

## `absolute_timestamp`

BRW-005 可以在有明确 `file_start_time` manifest 时
**机械地计算**：

```text
absolute_timestamp = file_start_time + elapsed_time_s
```

但：

- 不进行 Electrical matching
- 不进行 clock drift correction
- 不进行 Cycle mapping
- 不把该时间视为“同步已经验证”

如 `file_start_time` 缺失：

```text
absolute_timestamp = null
```

并写 warning。

---

# 6. Zarr contract

每个 Ultrasound DataAsset 建一个独立 group：

```text
waveforms.zarr/
└── U001/
    └── waveform
```

推荐 shape：

```text
(n_frames, n_samples)
```

当前样例：

```text
(3999, 1250)
```

推荐 dtype：

```text
int32
```

除非通过独立范围检查证明更小整数 dtype 安全。

禁止因为“看起来像 int16”就直接强制 int16。

Zarr attrs 建议记录：

```text
asset_id
source_file
frame_count
sample_count
parser_version
source_sha256
sampling_rate_hz = null
```

特别是：

```text
sampling_rate_hz = null
```

当前不能编造。

---

# 7. Multi-file behavior

同一 Experiment 有多个 TXT 时：

```text
U001.txt
U002.txt
U003.txt
```

要求：

- 每个 asset 单独解析
- 每个 asset 单独 Zarr group
- `frames.parquet` 可以合并 metadata
- 每一行保留 `ultrasound_asset_id`
- 每一行保留 `source_line_index`
- `frame_index_raw` 允许每个文件重新从 0 开始
- 不创建假的 experiment-global raw frame index 替代原始 frame ID

如果需要便于检索，可增加：

```text
event_order_index
```

但不能覆盖 `frame_index_raw`。

---

# 8. Parser implementation structure

推荐：

```text
src/battery_workbench/io/ultrasound/
├── __init__.py
├── custom_txt.py
├── schemas.py
├── validation.py
├── service.py
└── manifest.py
```

职责：

## custom_txt.py
只负责：
- 一行怎么拆
- 一帧怎么解析
- 文件怎么迭代

## schemas.py
定义：
- ParsedUltrasoundFrame
- AssetParseResult
- ExperimentParseResult

## validation.py
负责：
- section count
- frame ID
- elapsed time
- waveform length
- numeric conversion
- tail length
- monotonicity
- clipping/saturation diagnostics（只报告，不做修正）

## service.py
负责：
- Manifest → DataAsset
- 多文件解析
- frames.parquet
- Zarr
- parser manifest

## manifest.py
生成 parser_manifest.json。

Agent / API / Notebook 后续只调用 service。

---

# 9. Strict parser requirements

必须：

1. Raw TXT 只读。
2. 使用 DataAsset ID，不以文件名作为唯一身份。
3. 不静默跳过 invalid non-empty line。
4. 错误信息包含：
   - asset_id
   - filename
   - line number
   - failed field
5. 保留 unknown 字段。
6. 保留原始 frame index。
7. 保留 source line index。
8. 记录 SHA256。
9. Parser 前后 raw SHA256 一致。
10. 大波形写 Zarr，不写成 1250 个 metadata 列。
11. Zarr 写入后必须 round-trip 验证。
12. 不执行任何滤波或归一化。
13. 不计算 TOF。
14. 不计算 FFT / frequency features。
15. 不猜 sampling frequency。

---

# 10. Current sample acceptance facts

当前真实样例已独立确认：

```text
frame_count = 3999

frame_index_raw:
0 → 3998

sections_per_frame:
6

waveform_sample_count:
1250

unknown_tail_count:
16

first elapsed_time_s:
0.031217

last elapsed_time_s:
39980.03

median frame interval:
≈10.0 s
```

Agent 必须先检查当前仓库真实 DataAsset 是否仍然与此一致。

如果用户已替换/新增 TXT：

不要偷偷把测试 expected 改掉；
先报告 contract change。

---

# 11. Required parser manifest

输出：

```text
parser_manifest.json
```

至少：

```json
{
  "battery_id": "...",
  "experiment_id": "...",
  "parser": "custom_txt",
  "parser_version": "0.1.0",

  "source_assets": [],
  "source_sha256": {},

  "assets": [
    {
      "asset_id": "...",
      "source_file": "...",
      "frame_count": 0,
      "frame_index_min": 0,
      "frame_index_max": 0,
      "elapsed_time_min_s": 0.0,
      "elapsed_time_max_s": 0.0,
      "median_frame_interval_s": 0.0,
      "waveform_sample_counts": [],
      "waveform_dtype": "int32",
      "waveform_min": 0,
      "waveform_max": 0,
      "unknown_tail_lengths": [],
      "file_start_time": null,
      "absolute_timestamp_available": false,
      "sampling_rate_hz": null
    }
  ],

  "row_counts": {
    "frames": 0
  },

  "warnings": [],
  "output_files": {
    "frames": "frames.parquet",
    "waveforms": "waveforms.zarr",
    "parser_manifest": "parser_manifest.json"
  }
}
```

---

# 12. Tests FIRST

实现主逻辑前先补测试。

## A. Synthetic line parser

造：

```text
frame 7
elapsed = 70.031
1250 waveform samples
16 tail values
```

验证逐字段。

## B. Wrong section count

Expected：
明确 FormatError。

## C. Wrong waveform length

1249 / 1251 samples。

Expected：
明确 FormatError。

## D. Wrong tail length

Expected：
明确 FormatError。

## E. Invalid numeric waveform token

Expected：
明确错误并带 line/asset 上下文。

## F. Monotonic elapsed time

构造：

```text
0
10
20
15
```

Expected：
validation issue，不静默排序修复。

## G. Frame ID sequence

如果 raw ID 不连续：

- 不自动重编号
- 记录 warning/validation issue

## H. Multiple TXT assets

两个 DataAsset 都从 frame_index=0 开始。

Expected：
- 两个 asset 都保留 raw ID 0
- 通过 asset_id 唯一区分
- Zarr group 分开

## I. Zarr round-trip

写入 → 读取。

Expected：
- shape 相同
- dtype 符合契约
- 随机至少 20 个样本值完全一致

## J. Parquet round-trip

frames metadata 写入 → 读回。

Expected：
- provenance
- elapsed
- frame index
- waveform location
一致。

## K. Raw immutability

SHA256 before/after 一致。

## L. Current real-data integration

对当前真实 DataAsset 至少验证：

```text
3999 frames
frame 0
frame 1000
frame 2000
frame 3000
frame 3998
```

每帧：

```text
waveform length = 1250
```

并独立对照原 TXT 的：

```text
waveform[0]
waveform[10]
waveform[-1]
```

## M. Multi-file experiment synthetic integration

一个 Experiment 两个 TXT：

```text
U001
U002
```

Expected：
一个 `frames.parquet`，两个 Zarr groups。

---

# 13. Golden test

建立：

```text
tests/golden/ultrasound_expected.json
```

至少保存：

```text
frame 0
frame 1000
frame 2000
frame 3000
frame 3998
```

每个记录：

```json
{
  "asset_id": "U001",
  "source_line_index": 1,
  "frame_index_raw": 0,
  "elapsed_time_s": 0.031217,
  "waveform_sample_count": 1250,
  "waveform_checks": {
    "0": 123,
    "10": -456,
    "1249": 789
  }
}
```

重要：

> Golden expected values 不能由被测 parser 自己生成。

应通过：
- 独立读取
- 人工核对
- 或最简单 raw split 脚本
获得。

---

# 14. Optional parser-level diagnostics

BRW-005 可以统计，但不能“修正”：

```text
waveform min/max
mean sample amplitude
frame RMS summary
possible clipping count
constant/all-zero waveform count
waveform sample-count variability
```

这些只是 parser/structural diagnostics。

不要在 BRW-005 形成科研 feature table。

---

# 15. Scientific metadata guard

如果以下 metadata 未确认：

```text
sampling_rate_hz
transducer_center_frequency_hz
gain_db
pulse_mode
coupling
probe_position
```

则：

```text
null / unknown
```

Agent 必须明确报告缺失。

绝对禁止：

```text
sampling_rate_hz = 1250
```

因为 1250 是 samples/frame，不是 Hz。

也禁止：

```text
sampling_rate_hz = 1/10s
```

因为 10 s 是 frame interval，不是 waveform sampling interval。

---

# 16. Before finishing

必须运行：

```bash
pytest
ruff check <本次修改文件>
ruff format --check <本次修改文件>
mypy src
git diff --check
```

然后真实运行当前 Ultrasound DataAsset parser。

检查：

```text
frames.parquet
waveforms.zarr
parser_manifest.json
```

并做：

```text
Zarr random-value round trip
Parquet round trip
raw SHA256 before/after
```

---

# 17. Final handoff format

必须输出：

## Status
PASS / PARTIAL / FAIL

## Files changed

## Real ultrasound assets
- Battery
- Experiment
- Asset IDs
- Source TXT files

## Parsed results

| Asset | Frames | Frame IDs | Elapsed range | Samples/frame | Zarr shape |
|---|---:|---|---|---:|---|

## Raw integrity
SHA256 before/after

## Golden checks

## Outputs
- frames.parquet
- waveforms.zarr
- parser_manifest.json

## Tests
pytest / ruff / format / mypy / git diff

## Missing physical metadata
明确：
- sampling rate
- transducer information
等是否未知。

## Known limitations

明确未实现：

- BRW-006 Ultrasound QA
- filtering / denoising
- FFT
- TOF
- feature extraction
- synchronization
- ML
- Agent
- UI
