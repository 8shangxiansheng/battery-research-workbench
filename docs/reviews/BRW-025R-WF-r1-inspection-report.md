# BRW-025R-WF R1 — INSPECTION REPORT (12 项差距勘察)

Round 1 of BRW-025R-WF. Read-only: no code changed, no artifact written.
Scope: routes/WorkbenchShell、AnalysisWorkbench stepper、ResearchOverview、Models/Report/Waveform
workbenches、Assistant（drawer/context/后端 planner）、AdvancedPage、deep links、pending
action（fs/gate submission）、stale banners、localStorage 使用点。

Evidence anchors are `file:line` against the current worktree
(HEAD 68cbb68 "feat(BRW-025R-FE-R2)").

---

## 1. Current route map（现状路由图）

Top level (`frontend/src/pages/redesign/WorkbenchShell.tsx:66-72` AppRoutes):

```
/                        → ExperimentLibraryPage
/new, /new/:sessionId    → NewExperimentWizardPage
/runs                    → RunsPage（顶层，含 Back to library）
/experiments/:b/:e/*     → ExperimentLayout（AssistantProvider + Sidebar + topbar）
   index                 → Navigate → overview
   overview              → ResearchOverview（BRW-025R-OV 首屏）
   overview-classic      → OverviewPage（旧首屏，仍在路由中）
   waveform              → WaveformWorkbench
   analysis              → AnalysisWorkbench（内部 6 步 stepper）
   models                → ModelsWorkbench
   report                → ReportWorkbench
   advanced/:section     → AdvancedPage（parameters|evidence|lineage|artifacts|
                            runs|data|dataset-split；section=artifacts/workspace
                            → WorkspacePage）
   兼容重定向: modeling→models, reports→report, features→analysis,
            data/dataset-split/evidence/workspace/runs → advanced/<同名>
   *                     → Navigate → overview
```

AnalysisWorkbench 内部 stepper（`AnalysisWorkbench.tsx:28` + `TargetSelector.tsx:8-16`，
仅组件内 state，不进 URL）：

```
target → alignment → features → relationships → selection → dataset
```

关键观察：
- 主链 STEP5 Preview / STEP6 ML-safe Review / STEP8 Grouped Split 不是顶层路由；
  Preview 与 ML-safe Review 折叠在 `analysis` 页第 5/6 内部步骤中，Grouped Split
  埋在 `advanced/dataset-split`（`WorkbenchShell.tsx:63` 将 legacy `dataset-split`
  重定向到 advanced，`AdvancedPage.tsx:33` 以 legacy-view 渲染
  `DatasetSplitPage`）。
- 无 `/target`、`/features`、`/preview`、`/dataset`、`/split` 一级科学工作流路由。
- `overview-classic`（`WorkbenchShell.tsx:62`）与被替换的 legacy 页面共存。

## 2. Duplicated workflow states（重复的工作流状态）

同一科学事实存在两套平行模型，无 canonical read model：

- **A（旧 Overview 工作流推断）**：`lib/overview-workflow.ts:3-12`
  `overviewNextStep(status, workspace, hasModels)` —— 前端用 StatusBlock +
  WorkspaceSummary 推断“完善前置参数/复核模型结果/检查波形并确认闸门/配置特征分析”，
  只被 `overview-classic`（`OverviewPage.tsx:31`）使用，主链 ResearchOverview 不用它。
- **B（research-overview next_actions）**：后端
  `api/research_overview.py:448-473 _next_actions()` —— 基于 fs 验证状态生成
  PROVIDE_SAMPLING_RATE / CALIBRATE_TOF_GATES / REVIEW_ALIGNMENT /
  REVIEW_MODEL_BASELINES，ResearchOverview 消费（`ResearchOverview.tsx:263`）。
- **C（Assistant planner phases）**：`agent_assistant/planner.py:300-307,378-387,412-484`
  各 intent 分支硬编码 next_actions（"Check alignment/Inspect features/Build
  exploratory table/Open grouped splits/Create grouped split/Open report…"），
  语义与 B 重叠但 label 与 route 集合不同。
- **D（AnalysisWorkbench stepper）**：6 内部步骤 + WorkflowStepKey
  （`AnalysisWorkbench.tsx:28`），与 §2 Canonical workflow 的 10 STEP 集合不一致。

四套词汇并存：用户在 Overview、Analysis、Assistant 看到的“下一步”可能各不相同。

## 3. State-loss points（状态丢失点）

- **无任何 localStorage/sessionStorage**（`rg localStorage|sessionStorage src` 零命中）
  —— 这是好事（符合 task pack 红线），但也意味着：刷新/后退/深链后，
  target、selected features、preview spec hash、mode、分析步骤全部丢失，
  从 `analysis` 恢复时回到 stepper 第 1 步 target。
- AnalysisWorkbench 全部工作流 state 为组件 useState（`AnalysisWorkbench.tsx:29-33`），
  不进 URL 也不进 context provider；切到 models/report 再回来即清零。
- AssistantDrawer conversation 仅保留内存态（`AssistantDrawerV2.tsx:50-53`），
  后端 session 持久（`routes/assistant.py:52-67`），但 UI 只在 drawer 打开时同步
  `slice(-8)`。
- DatasetXYPreview 构建成功后 `built` 状态只在当前页显示（`AnalysisWorkbench.tsx:155`），
  离开页面即丢失，无全局 handoff。
- 实验切换：`AssistantProvider key={b/e}`（`WorkbenchShell.tsx:55`）+ `main` key
  remount（`WorkbenchShell.tsx:59`）隔离了 React state，但 react-query cache 键均含
  batteryId/experimentId（见 §15 grep 全部 queryKey），上下文不会串实验 —— 这一点
  已经达标。

## 4. Dead ends（死路）

- `overview-classic`（`WorkbenchShell.tsx:62`）：无入口链接指向它，是事实死路由；
  它内部的 `overviewNextStep` 推断与主链 next_actions 冲突（见 §2）。
- Analysis selection 步 ML-safe 模式无 split 时：提示去
  `/advanced/splits`（`AnalysisWorkbench.tsx:129`）—— 但 AdvancedPage 的 tab 名是
  `dataset-split`（`AdvancedPage.tsx:33`），`/advanced/splits` 落入
  `AdvancedPage` 的 fallback EmptyState"视图不可用"（`AdvancedPage.tsx:33` 三元链）。
  这是真实的断链：两处文本（129 与 160 行）都指向 404 等价页。
- dataset 步完成后的 handoff（`AnalysisWorkbench.tsx:159-161`）：同样指向
  `/advanced/splits` 断链；且"到 SOC 建模页训练"无按钮，纯文字。
- WaveformWorkbench 采样频率缺省时 TOF/波速 BlockedValue 卡仅提示"需要先提供采样
  频率"+ ParameterDialog（`WaveformWorkbench.tsx` 尾部 grid），但没有指向 Overview
  inline fs 提交的最短路径 deep link（用户需自行发现 Overview 有表单）。
- ModelsWorkbench 空态（`ModelsWorkbench.tsx:31` EmptyState）指向 `/analysis`，
  但"先构建数据集和分组划分"的 split 半段仍需用户自行走 `/advanced/splits` 断链。
- `/advanced/artifacts` 与 `/advanced/workspace` 混渲染 WorkspacePage
  （`AdvancedPage.tsx:33`），tab 列表里却没有 `workspace` 项（tabs 数组只有 7 项），
  用户从 UI 无法到达，另一个半死路由。

## 5. Inconsistent next-action wording（下一步文案不一致）

同一动作在不同表面用不同词汇：
- fs 缺失：Overview banner"阻断：采样频率未在参数注册表验证…"
  （`research_overview.py:498-503`）；Waveform TOF 卡"需要先提供采样频率"；Assistant
  next_actions 未含 PROVIDE_SAMPLING_RATE（`research_overview.py:454` 有，但 planner
  分支 `planner.py:284-307` 给的是 Check alignment/Inspect features）。
- split：Analysis 文案"ML-safe selection requires grouped split first / 模型安全特征
  筛选需要先建立分组划分"（`AnalysisWorkbench.tsx:129`）；models 空态"请先构建数据集
  和分组划分"（`ModelsWorkbench.tsx:31`）；route 目标一处写 `/advanced/splits`（断），
  AdvancedPage tab 名 `dataset-split`（`AdvancedPage.tsx:33`）。
- 闸门：ResearchOverview next_action"CALIBRATE_TOF_GATES 标定并冻结 TOF 双闸门（波形
  工作台）"（`research_overview.py:460-464`）；overview-classic `overviewNextStep` 用
  "检查波形并确认闸门"（`overview-workflow.ts:11`）。
- Report：planner"Open report"（`planner.py:464`）vs Overview next_actions 无
  OPEN_REPORT 类动作（`research_overview.py:466-473` 只有 REVIEW_MODEL_BASELINES）。

## 6. Deep-link failures（深链问题）

- 深链到 `analysis`、`models`、`report` 均能渲染，但**不恢复工作流位置**：
  `analysis` 内部 stepper 无 URL 表示（§3），深链后回到 target 步；models/report
  深链在无产物时显示 EmptyState + 文字指引（可接受），但指引目标含 §4 断链。
- 深链到 `/advanced/splits` → EmptyState"视图不可用"（真 bug，见 §4）。
- 深链到 `/overview-classic` 可达但无导航入口（幽灵路由）。
- 深链到 `/experiments/:b/:e` 无 section 时 `index → overview` 重定向（正常）。
- 深链到不存在的 section（如 `/advanced/foo`）→ EmptyState，未显示"前置条件 +
  精确下一步动作"（task pack §11 要求 prerequisite state + exact next action）。

## 7. Stale-state risks（过期状态风险）

- react-query 全局 `staleTime: 30s`（`main.tsx:13`）+ `refetchOnWindowFocus: false`：
  fs 提交后靠 submission service 显式 invalidate（`lib/submission.ts:46-57`
  SUBMISSION_QUERY_KEY_NAMES 9 个键）刷新 —— 这条链路是好的。
- 但 `research-overview` 键**不在** SUBMISSION_QUERY_KEY_NAMES 中：Overview 首屏
  的 readiness matrix/banner/next_actions 在 fs 提交后 30s 内仍显示 BLOCKED
  （staleTime 到期或手刷前）。Waveform 页 gate calibration 提交后 invalidate
  `gate-calibration`+`canonical-tof`（`CalibrationWorkbench.tsx:102,125-126`），但
  同样不失效 `research-overview`。
- 模型/数据集构建后：`DatasetXYPreview` 的 mutation onSuccess 仅回调 `onBuilt`
  （`DatasetXYPreview.tsx:114`），未见对 `results`/`splits`/`reports` 键的 invalidate
  （ModelsWorkbench 用 `["results",b,e]`，ReportWorkbench 用 `["reports",b,e]`、
  `["limitations",b,e]`、`["feature-correlations",...]`）—— 用户从 dataset 构建跳到
  models 页，30s staleTime 内可能看到旧空态（stale 数据被显示直至重挂载/refetch）。
  需在 R3 中把 workflow-context 与全部受影响键纳入统一 invalidation。
- research_overview 已有 stale 检测（feature_definition fs_version≠2.0.0 →
  refresh_required，`research_overview.py:304-315`），前端 `ResearchOverview.tsx:302`
  有显示 —— 但 Dataset/Model/Report 页面**没有**任何 stale 呈现（grep
  `stale|STALE|LEGACY` Models/Report 零命中），依赖链不可见（task pack §08 要求
  CURRENT/STALE/LEGACY/SUPERSEDED/MISSING 链式可见）。

## 8. Pending-action recovery gaps（待处理动作恢复差距）

- BRW-018R2 same-run resume：`submission.ts` 提供 PARTIAL→重试恢复（`ResearchOverview.tsx:66`
  ov-fs-retry），恢复成功后 invalidate 9 键 —— 但 `research-overview` 不在其中
  （§7 同一问题），Overview banner/readiness 不会立即翻转。
- 后端 Assistant session 有 `pending_user_action`（`session.py:86`、planner
  `WAITING_FOR_USER` 分支 `planner.py:202-209,279,423-429,473-474,556-575`），前端
  drawer 也渲染（`AssistantDrawerV2.tsx:111-114`）—— 但它只在 drawer 内可见，
  Overview/Workspace/Stepper 看不到全局 WAITING 态（task pack §09 要求 pending
  actions 全局可见）。
- ParameterDialog（Waveform 参数弹窗）与 Overview inline fs 表单是两个入口，但
  ParameterDialog 的提交结果不驱动 Overview inline 状态，也没有共享
  pending/resume 面板。
- gate calibration pending：CalibrationWorkbench 有提交/确认流，但无跨页
  "waiting"指示。

## 9. Proposed ScientificWorkflowContext（拟议方案，R2/R3 细化）

后端新增 read-only 聚合端点（零科学重算，全部读现成 artifacts）：

```
GET /experiments/{b}/{e}/workflow-context   (workflow-context/1.0)
{
  experiment_id, battery_id,
  target: {target_id, target_status},          # committed target（BRW-023 targets + assistant session）
  alignment: {alignment_status, eligible_count, excluded_count},
  features: {selected_feature_locators, feature_selection_source, feature_selection_status},
  preview: {preview_spec_hash, preview_mode},
  dataset: {dataset_id, dataset_status},
  split: {split_id, split_status},
  model_run: {model_run_id, model_status},
  report: {report_id, report_status},
  pending_action, blocking_reason,
  recommended_next_action,                    # typed: {action_id, step, route, label_en/zh}
  artifact_freshness,                         # {CURRENT|STALE|LEGACY|SUPERSEDED|MISSED} per artifact
  limitations
}
```

数据源全部现成：targets（`routes/features_v2` listTargets）、alignment summary、
materialized analyses（`AnalysisWorkbench.tsx:34` 已消费 listMaterializedAnalyses）、
datasets/splits（`routes/resources.py:158-175`）、baseline runs、reports、assistant
session（`routes/assistant.py`）、research_overview 的 fs/readiness/stale 逻辑
（`research_overview.py:448-473` 可复用）。实现要点：
- 推荐动作统一为一个函数产出（消灭 §2 四套词汇），route 字段给到真路由。
- 前端 `ScientificWorkflowContext` provider 挂在 ExperimentLayout（与
  AssistantProvider 同级），query key `["workflow-context", b, e]`；Stepper 七态
  （COMPLETE/CURRENT/READY/BLOCKED/STALE/NOT_STARTED/LIMITED）由它驱动；
  AnalysisWorkbench 内部 state 改为“draft + committed”双层（§10 的 draft guard）。

## 10. Proposed route map（拟议路由图，含 stepper 步 ↔ 路由映射）

保持 `/experiments/:b/:e/` 前缀，把 §02 canonical 十步映射为一级路由（stepper
为导航-only，点击 stepper 即导航，永不触发 build/train/report）：

```
STEP1  overview      （现有 ResearchOverview + Resume Research 按钮）
STEP2  target       （由 AnalysisWorkbench target 步拆出；选一次全局提交）
STEP3  alignment
STEP4  features
STEP5  preview      （feature-label preview + confirm spec hash）
STEP6  review       （ML-safe review；或并入 preview?step=mlsafe——R2 决定）
STEP7  dataset
STEP8  split        （顶层化，替换 /advanced/dataset-split 断链）
STEP9  models       （现有）
STEP10 report       （现有）
advanced/* 保留为只读细节区（parameters/evidence/lineage/runs/data）
```

- 修复 §4/§5 的 `/advanced/splits`→`/advanced/dataset-split` 断链（改指向
  `split`）。
- 移除或下线 `overview-classic` 幽灵路由（R3 保留重定向即可）。
- Assistant typed navigation：NextAction 增加 route/intent 字段（当前
  `session.py:54-58` 的 NextAction 只有 label，无 route —— planner 的
  `current_ui_route` `planner.py:80` 仅作上下文，不产出导航）。

## 11. E2E plan（W01–W31 布局，对应 13_E2E_SCENARIOS 的 10 场景）

沿用现有 Playwright+vitest 双轨（`tests/e2e-happy-path.test.ts` 等模式）：
- E2E1 happy path：overview→target→alignment→features→preview→dataset→split→
  models→report 全链，断言 stepper 状态迁移与 handoff 字段。
- E2E2 Browser Back/Forward：每步导航后 back/forward，断言不触发任何 POST
  （network 断言：导航期间零 build/train/report 请求）。
- E2E3 deep link：直接打开 `split?dataset=…` 等深链，断言恢复或显示前置
  条件卡（非 404/空白）。
- E2E4 stale chain：fs version 变更后 dataset/model/report 显示 STALE 徽标。
- E2E5 WAITING sampling-rate：Overview 提交 fs → same-run resume → 断言
  workflow-context + research-overview + assistant-session 全部 refetch。
- E2E6 impossible split：无数据集建 split → BLOCKED 态 + 精确 blocking_reason。
- E2E7 unsaved draft：target/features 草稿离开 → Save/Discard/Stay 三选一。
- E2E8 experiment switch：切换实验后所有 context 键换新值（无泄漏）。
- E2E9 agent next action：assistant 返回 typed OPEN_PREVIEW → 点击 → 路由跳转。
- E2E10 navigation artifact immutability：全链导航 network 抓包断言 GET-only。
- W01–W31 单元断言（vitest）：路由表、context provider 七态映射、draft guard
  reducer、typed action 校验、stale 链计算、isolation key 等。

## 12. Visual plan（16 张截图，viewport 1440×900）

按 15_VISUAL_ACCEPTANCE_MANIFEST.yaml 清单，基于真实 CELL_001 + 已激活 fs/TOF 的
demo 数据，用现有 screenshot 脚本模式（screenshot-brw025rov.mjs 等）新增
`screenshot-brw025wf.mjs`：
01 overview_resume_research / 02 workflow_stepper / 03 target_to_features_continuity /
04 features_to_preview_continuity / 05 preview_to_dataset_handoff /
06 dataset_to_split_handoff / 07 split_blocked_state / 08 model_to_report_handoff /
09 stale_artifact_chain / 10 waiting_global_state / 11 sampling_resume_global_refresh /
12 unsaved_draft_guard / 13 deep_link_prerequisite / 14 assistant_next_action /
15 experiment_switch_context / 16_full_workflow_desktop。

---

## 差距汇总（R2/R3 的输入）

| # | 差距 | 严重度 | 归属 |
|---|------|--------|------|
| G1 | 四套 next-action 状态机并存 | 高 | R2 |
| G2 | `analysis` 内部 stepper 不进 URL，刷新/深链回 target | 高 | R3 |
| G3 | Preview/ML-safe/Split 无一级路由（埋 advanced + legacy-view） | 高 | R3 |
| G4 | `/advanced/splits` 两处断链（AnalysisWorkbench.tsx:129,160） | 高 | R3（改 `/split`） |
| G5 | 无 ScientificWorkflowContext 后端 read model | 高 | R2 |
| G6 | fs/calibration 提交后 `research-overview` 不失效（30s stale 窗口） | 中 | R3 |
| G7 | dataset build 后 results/splits/reports 键不失效 | 中 | R3 |
| G8 | Dataset/Model/Report 页无 stale 呈现 | 中 | R2+R3 |
| G9 | pending WAITING 仅 drawer 内可见，非全局 | 中 | R2+R3 |
| G10 | `overview-classic`、`advanced/workspace` 幽灵/半死路由 | 低 | R3 |
| G11 | Models 空态 → split 指引走断链 | 中 | R3 |
| G12 | 无 unsaved-draft guard（Save/Discard/Stay） | 中 | R3 |
| G13 | Assistant NextAction 无 route 字段（无 typed navigation） | 中 | R2 |
| G14 | 深链 prerequisite 页缺失（EmptyState 不含精确下一步） | 中 | R3 |

零 localStorage/sessionStorage（合规）；实验隔离已通过 provider key + query key
参数达成（`WorkbenchShell.tsx:55,59`；全部 queryKey 含 b/e）。R2 端点设计必须
零科学重算（read-only 聚合），符合 master prompt "navigation 必须是 artifact-immutable"。
