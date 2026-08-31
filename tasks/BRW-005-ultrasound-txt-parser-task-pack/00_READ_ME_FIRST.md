# BRW-005 — Ultrasound TXT Parser Task Pack

把整个 `BRW-005/` 文件夹放到仓库：

```text
battery-research-workbench/
└── tasks/
    └── BRW-005/
```

然后让 Coding Agent：

1. 先读仓库根目录 `AGENTS.md`
2. 再读 `tasks/BRW-005/01_MASTER_PROMPT.md`
3. 第一轮只 Inspect
4. 第二轮 tests-first
5. 再实现 parser / storage

---

## BRW-005 的唯一目标

把原始 Ultrasound TXT DataAsset：

```text
TXT
↓
Frame parser
↓
Frame metadata
+
Raw waveform array
↓
frames.parquet
+
waveforms.zarr
+
parser_manifest.json
```

本阶段不做：

- 滤波
- 降噪
- 包络
- FFT / STFT / Wavelet
- TOF
- 超声特征
- Electrical–Ultrasound synchronization
- ML
- Agent
- UI

---

## 当前真实 TXT 基线

当前已确认样例：

```text
frames = 3999
frame IDs = 0..3998
semicolon sections/frame = 6
waveform samples/frame = 1250
unknown tail values/frame = 16

first elapsed_time_s = 0.031217
last elapsed_time_s  = 39980.03
median frame interval ≈ 10.0 s
```

重要：

> 约 10 s 是“帧采集间隔”，不是单条 1250 点波形的采样频率。

在没有确认 waveform sampling frequency `fs` 前：

禁止输出：

```text
absolute TOF in μs
frequency axis in Hz/MHz
center frequency in Hz/MHz
```

---

## 推荐输出

```text
data/processed/ultrasound/{battery_id}/{experiment_id}/
├── frames.parquet
├── waveforms.zarr/
│   ├── U001/
│   │   └── waveform
│   ├── U002/
│   │   └── waveform
│   └── ...
└── parser_manifest.json
```

`frames.parquet` 保存 metadata/provenance；
大波形保存在 Zarr，不把 1250 个采样点展开成 1250 列 Parquet。
