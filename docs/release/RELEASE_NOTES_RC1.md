# Release Notes — BRW-RC1 (Scientific Workbench Release Candidate)

基线 commit `3a8a1af`（BRW-025R-WF）之上的收口变更。无新科学功能。

> **历史快照说明**：本文件只记录 RC1 基线及其冻结工件，不代表后续 `main` 的完整功能列表。后续加入的 Cohort/LOBO API、温度目标数据门和固定模型策略扩展，不回溯改变本 RC1 的评估结果。当前状态见[使用指南](../USER_GUIDE.md)和[扩展能力状态](../architecture/future-scientific-extension-contracts.md)。

## 科学状态（canonical: CELL_001/EXP_001）
- Canonical Envelope-Peak TOF 激活：3995/3995 VALID（fs 50 MHz 来自参数注册表 VERIFIED；GC-TOF::e401fecb FROZEN v20）；tof_us 15.52–16.08 µs。
- 新 CURRENT 链：DS::83013a61…（X 含 tof_us）→ SPLIT::23ebb24f…（LOGO/cycle）→ 5 固定基线（fold1 有限评估）→ REPORT::5b6cf84d…（JSON/MD/HTML）。
- 结论（如实）：无模型跑赢 Dummy（30.72 %MAE）。fold0 TRAIN-only 规则选择为空 → FEATURE_SELECTION_STABILITY_LIMITED。
- 旧链（DS::6a3142e5 / REPORT::62c70630）保留为 LEGACY/SUPERSEDED，未替换。

## 修复（release blockers）
1. `/analysis` 白屏：生产入口 BrowserRouter → **data router**（useBlocker 依赖）；深链/Back/Forward/Refresh 全过。
2. 报告/概览陈旧身份：collector 与 research_overview 的 hardcode 工件 ID → 动态"最新评估链"解析；TOF_UNAVAILABLE_OR_BLOCKED 限制仅在真实溯源缺失时出现。
3. run-less 测试探针提交造成伪 WAITING_FOR_USER 死路 → 仅带 run 的提交参与 pending 判定。
4. preview/数据集词表：tof_us 可作为 X（只读自工件）；rms/envelope 别名补齐；physical-features 目录含 canonical TOF 块。
5. Agent：新增 WHAT_NEXT（与 workflow-context 同一推荐）与 MODEL_TOF_FRESHNESS（模型是否用新 TOF 的显式证据回答）。

## 复现/完整性
- Clean-room raw→report（fresh root）计数/ID 与 canonical 全等；Run B 同 spec：DATASET/SPLIT/MODELING REUSED（无重复拟合）。
- 只读遍历前后 200 工件 SHA256 零变化；raw SHA256 重算一致。
- 测试门：backend pytest 全绿；frontend 248 通过/1 跳过；tsc/eslint/build 通过；ruff 通过（mypy 受 numpy stub 的 py3.13 限制，记录为环境项）。

## 已知限制（不支持的主张）
单电池、两循环、provisional timebase、无独立验证组、无跨电池验证、SOH 状态过少、温度通道缺失、预测优势弱。禁止表述：production-ready / cross-battery validated / true SOC / 绝对物理真值。

## 冻结
见 RC1_FREEZE_POLICY.md。建议 tag `brw-rc1`（发布需维护者批准）。不自动创建 RC2。
