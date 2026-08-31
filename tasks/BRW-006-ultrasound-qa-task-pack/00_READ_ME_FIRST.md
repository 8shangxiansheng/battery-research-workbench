# BRW-006 — Ultrasound QA Task Pack

放到：`battery-research-workbench/tasks/BRW-006/`。

执行顺序：先读 `AGENTS.md` → 再读 `01_MASTER_PROMPT.md` → Inspect only → Tests RED → 实现 QA → 真实数据验收。

## 唯一目标

对 BRW-005 的：

```text
frames.parquet + waveforms.zarr + parser_manifest.json
```

做：结构完整性、时间质量、波形幅值质量、异常帧、跨帧稳定性 QA，并输出 JSON/HTML/图/表。

## 允许的 QA-only 指标

`min/max/mean/std/RMS/P2P/zero fraction/constant frame/adjacent-frame correlation/ΔRMS/ΔP2P/Δmean`。

这些只用于 QA，不生成正式 `ultrasound_features.parquet`。

## 禁止

滤波、降噪、alignment、TOF、FFT 物理频率、STFT/Wavelet 科研分析、同步、ML、Agent、UI。
