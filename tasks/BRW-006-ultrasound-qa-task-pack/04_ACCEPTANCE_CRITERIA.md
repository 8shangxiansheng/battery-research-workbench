# BRW-006 Acceptance Criteria

- [ ] 只读 BRW-005 processed outputs
- [ ] input Parquet/Zarr 不变
- [ ] metadata frame count vs Zarr shape 一致
- [ ] sample count / dtype / locator / asset group 验证
- [ ] provenance 完整
- [ ] elapsed min/max/monotonicity/interval/gap 检查
- [ ] waveform min/max/mean/std/RMS/P2P/zero fraction
- [ ] all-zero / constant frame detection
- [ ] possible saturation（不误称 confirmed clipping）
- [ ] adjacent correlation / ΔRMS / ΔP2P / Δmean
- [ ] JSON / HTML / 3 tables / 8 figures
- [ ] deterministic PASS/PASS_WITH_WARNINGS/FAIL
- [ ] sampling_rate_hz 仍 unknown/null
- [ ] no TOF / physical Hz/MHz / filtering / alignment / feature dataset
- [ ] synthetic tests + real integration
- [ ] pytest / ruff / format / mypy / git diff 全部符合要求
