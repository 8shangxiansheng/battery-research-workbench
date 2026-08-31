# Human Review Checklist

- [ ] metadata rows = 3999（当前 baseline）
- [ ] Zarr shape = 3999 × 1250
- [ ] dtype int32
- [ ] selected raw waveforms 使用 sample index
- [ ] amplitude 未错误标注 V/Pa
- [ ] heatmap 可读且 display downsampling 不影响 QA 数值
- [ ] RMS/P2P/DC/correlation 曲线合理
- [ ] anomalies 没有自动删除 outlier frame
- [ ] possible saturation 未误称 confirmed clipping
- [ ] sampling rate 仍 unknown
- [ ] no TOF / physical frequency / filtering / alignment
- [ ] frames.parquet 与 Zarr content checksum 前后不变
