# BRW-RC1 Thesis Figure Inventory

| 图 | 内容 | 来源截图 | 数据工件 |
|---|---|---|---|
| Fig-1 | 系统架构分层图 | —（手绘/README） | — |
| Fig-2 | 同步流程与 provisional timebase | 02_rc1_metadata_readiness | synchronization_manifest.json |
| Fig-3 | 单帧波形 + Hilbert 包络 + surface/bottom 闸门 + 峰位 | 03_rc1_waveform_tof, 04_rc1_gate_calibration | waveforms.zarr + GC-TOF::e401fecb |
| Fig-4 | canonical tof_us 分布（15.52–16.08 µs, median 15.96） | 03 | canonical_tof.parquet / audit |
| Fig-5 | Reference SOC 时间序列（回顾性参考标签语义） | 05_rc1_target_soc | event_labels.parquet |
| Fig-6 | 特征目录（TD/FD + 物理 + canonical TOF） | 06_rc1_feature_catalogue | /feature-definitions |
| Fig-7 | X/y 预览与行溯源、排除原因分解 | 07/08 | feature-label-preview (PREVIEW::a1eb…) |
| Fig-8 | ML-safe held-out 遮蔽证明（Network 响应体） | 09_rc1_ml_safe_heldout | SPLIT::23ebb24f assignments |
| Fig-9 | 模型对比（5 固定基线 vs Dummy，有限评估） | 12_rc1_model_comparison | model_comparison.json |
| Fig-10 | 工作流连续性 stepper + 推荐下一步 | 16_rc1_workflow_stepper, 15 | workflow-context |
| Fig-11 | 证据链报告页 | 13/14 | REPORT::5b6cf84d |
| Fig-12 | 复现性（clean-room Run A/B、hash 不变性） | 18_rc1_reproducibility | RELEASE_MANIFEST.json |
