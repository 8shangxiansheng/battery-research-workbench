# BRW-RC1 Freeze Policy

RC1（`docs/release/RELEASE_MANIFEST.json`）冻结后仅允许：
1. critical bug fix（阻断 primary path / 数据完整性 / 泄漏防护）
2. documentation
3. thesis assets（图、表、附录）
4. demo assets（截图、runbook 微调）

不允许在 RC1 线上进行：
- 新科学公式 / 新 TOF 方法 / 新特征族 / 新 Target
- 新 split 策略 / 新模型族 / 调参能力
- 新 Agent 工具类别 / 报告语义变更

任何科学定义变更 → 开新 release line（由维护者决定，不自动创建 BRW-RC2）。

建议 tag：`brw-rc1`（推送/发布需维护者显式批准）。
