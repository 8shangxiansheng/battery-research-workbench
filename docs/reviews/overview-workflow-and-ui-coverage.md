# 分析流程 UI 覆盖审查与概览重构

日期：2026-09-08。范围：当前 React 路由、组件、API client 和对应服务实现的静态追踪；概览页另做真实 API 浏览器验证。不是全站科学结果重新验收。

## 结论

分析主干已有页面，但“有按钮/卡片”不等于“端到端闭环”。当前不能宣称所有分析功能已完整体现在 UI。

| 环节 | 现有入口 | 覆盖与未完成项 |
|---|---|---|
| 实验与资产导入 | 实验库 / NewExperimentWizardPage | 有导入、资产预览和生命周期流程；本轮未重新提交原始文件 |
| 电学 / 超声 QA | Advanced → Data | 有计数、重复时间戳与同步摘要；不是完整 QA 诊断图浏览器 |
| 时间基准与参数 | Advanced → Parameters；概览原地抽屉 | 采样率可保存来源并刷新；缺校准文件上传、时间锚点更新与验证闭环 |
| 波形查看与闸门 | WaveformWorkbench / WaveformPlot | 有 zoom/pan/hover、选择、确认 gate；跨资产帧定位仍需完善 |
| 代表帧标定 | CalibrationWorkbench | 有代表帧、模板、诊断及冻结入口；调整后的 gates 没有随冻结请求提交，不能视为调整已持久化 |
| 不同特征对应不同窗口 | FeatureCatalogue / CalibrationWorkbench | 有模板和 feature metadata；通用分析选择仍以名称字符串传递，未完整保留 FeatureLocator 的 gate/tof 身份 |
| 闸门对应电学状态 | FrameContextPanels | 同帧共享事件的原则已有体现；WaveformWorkbench 只获取前 50 个事件，后续帧无法完整对应；DTO 未暴露 sync_error_s、资产身份和完整时间戳 |
| 特征提取与物理特征 | Waveform → PhysicalFeatureCards；Analysis | 有物理特征和 TD/FD 目录；定义存在不代表已计算/已验证。物理特征按 values[frameIndex] 寻址，非连续/跨资产帧需审查 |
| SOC / 温度 / SOH 相关性 | Analysis → FeatureRelationship | 有 SOC Pearson/Spearman、充/放/静置分组、温度可用性和 cycle 级 SOH 概览；没有完整混杂控制、组级重采样推断或通用条件切片交互 |
| TRAIN-only 特征选择 | Analysis | 有模式、split/fold 参数；已有分析匹配用 selected_features.some，任一重叠不足以证明整组选择 ML-safe |
| 数据集与划分 | Advanced → DatasetSplit | 有构建请求和分组划分；规格/复用不等于已执行完整训练流水线 |
| 模型评估 | Models | 有 Dummy 结论、宏观/分折指标和特征面板；无超参数调优 API；当前主页面主要用于结果查看 |
| 报告与可追溯性 | Report / Advanced Evidence、Lineage、Artifacts、Runs | 有报告请求、JSON 导出、证据与运行记录；当前结果与报告快照仍需区分 |
| Research Assistant | 顶栏全局 Drawer | 已接入卡片问题上下文；助手服务未连接，不发送或伪造 AI 回答 |

## 优先修复的既有缺口

1. **标定冻结不接收调整值**：`frontend/src/components/workbench/CalibrationWorkbench.tsx:92` 仅提交 confirmed_by/calibration_basis；本地 gates 没有传入。另 `:142` 包络开关两分支完全相同，开关无效。
2. **TRAIN-only 匹配过宽**：`frontend/src/pages/redesign/AnalysisWorkbench.tsx:115` 使用部分重叠识别匹配分析；需精确验证候选集合、split/fold、选择依据及 FeatureLocator。
3. **电学上下文覆盖不完整**：`frontend/src/pages/redesign/WaveformWorkbench.tsx:25` 固定前 50 行；应有资产限定的单帧事件 API，保留 sync_error_s。不能按 Cycle 或 gate sample range 重新同步。
4. **物理特征寻址隐含连续编号**：`frontend/src/components/workbench/FrameContextPanels.tsx:20` 直接数组下标；需明确 frame identity，而不是依赖样例恰好从 0 连续编号。
5. **canonical 状态固定返回**：`src/battery_workbench/api/service.py:162` 当前固定 PROVISIONAL / BLOCKED / NOT_READY。UI 已根据响应分支，但真实数据无法仅靠保存参数转成“验证通过”。

以上属于科学工作流/契约问题，本轮仅审查列出，没有顺带更改科学逻辑。

## 本轮落地

- 概览只保留一个深色 Primary CTA：状态未知时等待；同步/TOF 阻断时原地完善前置；就绪后引导闸门、特征配置或模型复核。不自动提交科学任务。
- 采样率继续使用现有 Dialog，显式 verified=false；保存后刷新 parameters/status/workspace-summary/data-quality/synchronization/features，不伪造绿色验证徽标。
- 同步/SOH Drawer 展示依据与 API 缺口；超参数快捷入口明确“不支持调优”，没有假表单和假提交。
- 两张真实 API 预览图。当前真实事件没有 timestamp，电压/电流图明确使用返回事件顺序，非时间轴、非完整循环。A-scan 是首个可定位帧，不声称代表性；闸门仅展示已有同长度区间。
- Assistant 从悬浮按钮迁入顶栏，卡片上下文进入同一 Drawer；实验切换时重置上下文。不实现 BRW-027。
- 12 列自适应网格、24/32 px 内容间距、深色主按钮、绿色解析状态、琥珀阻断/基准诊断、等宽数字。
- 实际截图发现并修复 shadcn Sidebar 的 Tailwind 4 CSS variable 宽度兼容问题（原来侧栏遮挡正文）；同时移除嵌套 main landmark。

## 验证

- 新增 workflow 单测 6 项、交互单测 4 项；已验证先 RED 后实现。
- 9 组 frontend tests 共 63 项通过；typecheck、lint、build、git diff --check 通过。
- 真实本地 API + 浏览器只读检查：控制台 pageerror 0、API 写请求 0、390 px 横向溢出 false、概览 WCAG A/AA axe violations 0。自动扫描不等于完整无障碍认证。
- 截图在 `docs/ui/screenshots/overview-workflow/`：1440×900、全页、前置条件、采样率 Dialog、上下文助手、移动端。
- 本轮没有修改后端、数据、scientific contracts、依赖配置；没有 commit/push。
- 限制：Plotly 现有主 bundle 仍超过 500 kB；未宣称覆盖率达到 80%；未运行会生成真实科学产物的旧 E2E。人工最终视觉验收仍待用户确认。

## 设计技能说明

使用 maestro-impeccable 的产品工作台原则约束视觉与交互。本机 CLI 缺少其要求的 capabilities/runtime 协议，未创建或声称完成正式技能 Session；采用项目原有测试/构建/真实截图验证。
