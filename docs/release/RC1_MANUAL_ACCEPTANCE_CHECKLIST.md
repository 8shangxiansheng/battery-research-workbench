# BRW-RC1 Manual Acceptance Checklist

评审人：Qoder agent（R2）· 时间：2026-09-21/22 · 证据：docs/reviews/BRW-RC1-r2-manual-acceptance.md + docs/ui/screenshots/brwrc1/

| 项 | 结果 | 证据 |
|---|---|---|
| Raw checksums 重算且不变 | PASS | r1 §2 + manifest（8536d395…/8e196837…） |
| CELL_001/EXP_001 锁定 | PASS | manifest battery/experiment |
| Final ParameterSet 记录 | PASS | PS::3b512b82…（USER_SUPPLIED/VERIFIED） |
| Final GateCalibrationRecord（experiment-specific, frozen） | PASS | GC-TOF::e401fecb… v20 FROZEN |
| Canonical TOF 人工验 ≥5 帧（波形级包络复算） | PASS | §H 5/5 OK |
| sync/ambiguous/composite identity | PASS | ambiguous 4 保留；20/20 回源 |
| MeasurementEvent→feature→electrical→Target ≥5 | PASS | §K 5/5 |
| Overview 人工验 | PASS | 截图 01/02 |
| sampling missing→Saving→Saved→same-run resume | PASS | clean-room MISSING_SAMPLING_RATE + 回归套件 |
| Gate Calibration UI | PASS | 截图 04 |
| Reference SOC 语义（非真实 SOC） | PASS | 截图 05 + Agent disclaimer |
| demo X + exactly one y 预览 | PASS | PREVIEW::a1eb1817… |
| ambiguous excluded row 检查 | PASS | ME::…691 candidate_count=3, identity null |
| Exploratory ≠ ML-safe | PASS | PREVIEW_DRAFT + ML-safe fold 视图 |
| HELD_OUT y server-redacted（Network 证据） | PASS | 响应体 target=null + y_redacted |
| Final Dataset materialize + ID | PASS | DS::83013a61…（3995 行，TOF 溯源入 manifest） |
| Grouped split，无 Random Frame Split | PASS | SPLIT::23ebb24f LOGO/CYCLE |
| 固定 5 模型无 tuning | PASS | model_comparison.json |
| metrics 读自当前工件 | PASS | Dummy 30.72（Overview/Models/Report 一致） |
| 是否 beat Dummy 明示 | PASS（结论：否） | §W |
| 模型用当前 canonical TOF 明示 | PASS（是，含溯源） | §X + MODEL_TOF_FRESHNESS 回答 |
| Report JSON/MD/HTML、no retrain、数值有证据 | PASS | REPORT::5b6cf84d |
| Agent 10 对话 | PASS | RS::b3ed85409892 |
| 全工作流人工走查 + Back/Forward/DeepLink/Refresh | PASS | 走查 4/4（含 /analysis 白屏修复） |
| CURRENT/STALE/LEGACY/SUPERSEDED 审计 | PASS | freshness 全 CURRENT；旧链 LEGACY |
| RELEASE_MANIFEST.json | PASS | docs/release/ |
| Clean-room fresh root raw→report | PASS | Run A counts/IDs 全等 |
| Same-spec rerun REUSED（不重拟合） | PASS | Run B |
| 只读 UI/Agent 工件 hash 不变 | PASS | 200 文件 0 变化 |
| 20 张真实截图 | PASS | brwrc1/01–20 |
| limitations/unsupported claims 诚实 | PASS | release notes §限制 |
| 全套测试门 | PASS | 见 release notes |
