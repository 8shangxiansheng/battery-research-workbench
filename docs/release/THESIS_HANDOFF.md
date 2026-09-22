# BRW-RC1 Thesis Handoff

系统：Battery Research Workbench（超声–电气多模态电池实验工作台）
冻结工件身份见 `docs/release/RELEASE_MANIFEST.json`；截图 `docs/ui/screenshots/brwrc1/`。

| 论文章节 | 系统对应 | 证据位置 |
|---|---|---|
| Architecture | 分层：parsers → synchronization → MeasurementEvent → features/parameters/gates → datasets/splits → modeling → reporting → API → UI → Agent | README.md, docs/development-plan.md |
| Data ingestion | manifest 驱动 intake（Battery/Experiment/DataAsset，文件名非身份） | data/raw/manifests, intake sessions |
| Synchronization | 绝对时间戳 → 最近电记录（±容差）；provisional timebase；4 ambiguous 显式保留、不自动择近 | synchronization_manifest.json, 截图 02 |
| MeasurementEvent | 1 帧 = 1 事件；复合身份 (electrical_asset_id, record_locator)；sync_error_s 持久化 | measurement_events.parquet, 截图 08 |
| Parameters/Gates | Parameter Registry（fs 用户提交、VERIFIED，禁 hardcode）；experiment-specific GateCalibrationRecord（FROZEN v20） | PS::3b512b82…, GC-TOF::e401fecb…, 截图 03/04 |
| Feature Extraction | 33 TD/FD 目录（golden 对齐）+ gate-local 物理特征（SWA/BOTTOM_AMP/BPS/XCorr 诊断） | /feature-definitions, 截图 06 |
| TOF | canonical SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1：tof_samples=bottom−surface；tof_us=samples/fs×1e6；3995/3995 VALID，15.52–16.08 µs | canonical_tof.parquet + audit, 截图 03 |
| Target labels | Reference SOC = 回顾性分段归一化参考标签（非真实 SOC） | /targets, 截图 05 |
| Feature–Label Table | event 粒度 X/y 预览、行溯源、排除原因分解（AMBIGUOUS_SYNC 等） | feature-label-preview, 截图 07/08 |
| Leakage-safe evaluation | Grouped LOGO split（cycle 分组）；HELD_OUT y 服务端遮蔽；TRAIN-only 特征选择 + 用户确认门 | split_manifest/leakage_audit, 截图 09 |
| Models | 固定 Dummy/Linear/Ridge/RF/GB，无 tuning；fold1 有限评估：无模型跑赢 Dummy(30.72%) | model_comparison.json, 截图 12 |
| Agent | 只读工具层 + ClaimGuard + held-out guard + typed navigation；与 workflow-context 单一事实源一致 | 截图 15 |
| Evidence/Reproducibility | 报告 JSON/MD/HTML 全数值带证据引用；clean-room raw→report 复现；同 spec 重跑 REUSED；只读交互 0 hash 变化 | RELEASE_MANIFEST.json, 截图 13/14/18 |
| Results & Limitations | 见清单（单电池/两循环/provisional timebase/预测优势弱…） | scientific_report.json |
