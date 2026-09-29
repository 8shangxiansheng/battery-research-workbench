# 科学工作流（V2 页面结构）

用户逐步操作说明见[工作台使用指南](../USER_GUIDE.md)。当前主路径为：

**Overview**（实验状态、限制、下一步）→ **Waveform**（波形和闸门）→
**Analysis**（Target → Alignment → Features → Relationships → Selection → Dataset）→
**Split**（分组划分，按当前工作流状态进入）→ **Models**（评估）→ **Report**。

Parameters、Evidence、Lineage、Assets、Quality、Sync、Events 和 Runs 等细节属于高级检查或上下文入口，不作为顶层主导航步骤。

## 交互与科学状态

- Workflow Stepper 与后端 workflow context 联动；BLOCKED / WAITING 状态应给出原因和恢复路径。
- 波形缩放和平移不改变原始波形；draft gate 经用户确认后才成为 committed gate。
- 特征目录保留 CORE / DERIVED / AUXILIARY 等分组。TOF 前置条件不足时为 `null + reason`，绝不伪造为 0。
- Relationships 支持 Exploratory 与 ML-safe 分析模式；指标由 API 提供，前端不自行计算科学量。
- ML-safe 选择只使用训练组；held-out 标签由后端遮蔽。Grouped split 不足时保持阻断，不回退为 random-row split。
- Models 与 Report 应显示评估范围、Dummy baseline 和产物新鲜度；历史/过期产物不能支撑当前结论。
- Research Assistant 是全局 Drawer，用于基于当前工作流上下文提供导航和解释；不代表 BRW-027 Agent intelligence 已启用。
