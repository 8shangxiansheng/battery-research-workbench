# BRW-025R-WF R2 — INSPECTION REPORT (实施后勘察)

Round 2 of BRW-025R-WF. Read-only: no code changed, no artifact written.
Scope: R1 提出的 14 项差距（G1–G14）在 R2 中的闭合情况；对照 master prompt
全部完成标准逐项评估；标记 R3 仍需的工作。

Evidence anchors are `file:line` against the current worktree
(HEAD 68cbb68 + uncommitted R2 changes).

---

## R1 差距闭合矩阵

| R1 # | 差距 | R2 状态 | 证据 |
|------|------|---------|------|
| G1 | 四套 next-action 状态机并存 | **部分闭合** | 后端 `workflow_context.py:590-631` 统一了推荐动作逻辑；前端 `deriveStepperStatuses` + `ResumeResearchButton` + `WaitingBanner` + `AssistantDrawerV2 TYPED_NAV_MAP` 均消费同一 `recommended_next_action`。但 `lib/overview-workflow.ts` 旧推断器仍存在（仅 overview-classic 消费），`research_overview.py _next_actions()` 仍独立生成 next_actions（Overview Quick Actions 消费），两套与 workflow-context 并存。 |
| G2 | analysis 内部 stepper 不进 URL | **未闭合** | `AnalysisWorkbench.tsx:22` 仍为 `useState<WorkflowStepKey>("target")`，6 步内部 stepper 无 URL 表示。深链/刷新回 target 步。 |
| G3 | Preview/ML-safe/Split 无一级路由 | **未闭合** | Preview 折叠在 `analysis` 页 dataset 步；Split 仍在 `advanced/dataset-split`。R2 决定不拆路由（保持 analysis 页内 6 步 + 全局 stepper 导航），但 master prompt 要求的 STEP5–STEP8 独立路由未实现。 |
| G4 | `/advanced/splits` 两处断链 | **未闭合** | `AnalysisWorkbench.tsx:129` 和 `:160` 仍指向 `/advanced/splits`（不存在的 tab），应改为 `/advanced/dataset-split` 或全局 stepper SPLIT 步。 |
| G5 | 无 ScientificWorkflowContext 后端 read model | **已闭合** | `workflow_context.py` 767 行完整实现；`resources.py:62-80` 路由注册；`WorkflowContextPayload` 前端类型 `client.ts:1325-1359`；`useWorkflowContext` hook `useWorkflowContext.ts:17-27`。 |
| G6 | fs/calibration 提交后 research-overview 不失效 | **部分闭合** | `useInvalidateWorkflow()` `useWorkflowContext.ts:30-38` 显式 invalidate `research-overview` + `assistant-session` + `workflow-context`。但 `submission.ts` 的 `SUBMISSION_QUERY_KEY_NAMES` 是否已包含 `research-overview` 需 R3 验证。 |
| G7 | dataset build 后 results/splits/reports 键不失效 | **部分闭合** | `useInvalidateWorkflow()` 提供了统一 invalidate 函数，但 `DatasetXYPreview.onBuilt` 回调（`AnalysisWorkbench.tsx:152`）尚未调用它。需 R3 在 dataset build 成功后调用 `invalidateWorkflow()`。 |
| G8 | Dataset/Model/Report 页无 stale 呈现 | **部分闭合** | 全局 stepper 显示 STALE 色（`WorkflowStepperV2.tsx:36-43` amber），但 Dataset/Model/Report 页面本身仍无 stale banner 或 freshness badge。`deriveStepperStatuses` 正确映射 freshness → STALE。 |
| G9 | pending WAITING 仅 drawer 内可见 | **已闭合** | `WaitingBanner.tsx` 在 `WorkbenchShell.tsx:55` 全局渲染，所有页面可见。`pending_action` 来自 workflow-context，与 drawer 内 `pending_user_action` 同源。 |
| G10 | overview-classic / advanced/workspace 幽灵路由 | **未闭合** | `WorkbenchShell.tsx:58` 仍保留 `overview-classic` 路由；`AdvancedPage` 混合渲染未改。低优先级。 |
| G11 | Models 空态 → split 指引走断链 | **未闭合** | `ModelsWorkbench.tsx` 空态文案未改（需 R3 验证具体指向）。 |
| G12 | 无 unsaved-draft guard | **组件已建，未接线** | `useDraftGuard.ts` 完整实现（Save/Discard/Stay + useBlocker），但 `AnalysisWorkbench.tsx` 未调用 `useDraftGuard`。target/features 草稿离开仍无保护。 |
| G13 | Assistant NextAction 无 route 字段 | **已闭合** | `AssistantDrawerV2.tsx:38-50` `TYPED_NAV_MAP` 映射 action_id → step → route；typed navigation actions 直接 `navigate()` 不提交消息。后端 `typed_actions` 提供 action_id + route。 |
| G14 | 深链 prerequisite 页缺失 | **组件已建，未接线** | `PrerequisitePanel.tsx` 完整实现，但未被任何路由/页面消费。深链到 BLOCKED 步仍显示默认页面内容而非 prerequisite 卡。 |

**汇总**：14 项差距中 4 项已闭合（G5, G9, G13 + G8 stepper 部分），4 项部分闭合（G1, G6, G7, G8 页面），2 项组件已建未接线（G12, G14），4 项未闭合（G2, G3, G4, G10/G11）。

---

## 对照 Master Prompt 完成标准逐项评估

### BRW-025R-WF COMPLETE — 端到端工作流连续性

| 要求 | 状态 | 证据 / 差距 |
|------|------|-------------|
| 唯一 ScientificWorkflowContext，UI+Assistant 共用 | **PASS** | `workflow_context.py` 单一 read model；前端 `useWorkflowContext` 被 WorkbenchShell（Stepper + WaitingBanner）、ResearchOverview（ResumeResearch）、AssistantDrawerV2 共用。 |
| workflow stepper 显示 COMPLETE/CURRENT/READY/BLOCKED/STALE/LIMITED | **PASS** | `WorkflowStepperV2.tsx` 7 态全实现；`deriveStepperStatuses` 正确映射。前端测试 W05 验证全部 7 态。 |
| Overview 有 Resume Research | **PASS** | `ResearchOverview.tsx:335-346` `ResumeResearchButton` 消费 `recommended_next_action.route`。 |
| Target 选一次，下游继承 | **PARTIAL** | 后端 `steps.TARGET.committed.target_id` 传递到 features/dataset；但 AnalysisWorkbench `targetId` 是组件 useState，刷新丢失（G2 未闭合）。 |
| Features 直接交给 Preview | **PARTIAL** | 后端 `steps.FEATURES.committed.selected_features` → `steps.PREVIEW` 判断 `features_selected`；但前端 Preview 折叠在 analysis 页 dataset 步，无独立路由。 |
| Preview confirmed spec 交给 Dataset | **PARTIAL** | 后端 `steps.PREVIEW` 注释 "preview 是页面内 draft；物化数据集即确认完成"；前端 `spec_hash` 从 preview 传给 `DatasetBuildButtons`（`AnalysisWorkbench.tsx:153`），但无显式 confirm 步骤。 |
| Dataset → Split 连续性 | **PASS** | 后端 `steps.SPLIT` 绑定 `dataset_id`；`_split_latest` 过滤 committed dataset。 |
| Split 正确 gate Models | **PASS** | 后端 `steps.MODELS` 检查 `split_ready`（`readiness_status == READY_FOR_LIMITED_EVALUATION`）；测试 W24 验证 NOT_READY → BLOCKED。 |
| Model → Report 连续性 | **PASS** | 后端 `steps.REPORT` 检查 `models` 非空；`_report_latest` 读最新报告。 |
| Back/Forward/deep link 不重复 build/train/report | **PASS** | Stepper navigation-only（`WorkflowStepperV2.tsx:56-62` 仅 `navigate()`）；测试 W18 验证 stepper 渲染无 POST。后端 `meta.read_only: true, no_recomputation: true`。 |
| draft 与 committed 分离 | **PARTIAL** | 后端 `_dataset_latest` 排除 `SPEC_PENDING_RUN`（draft）；`_dataset_drafts` 单独报告。前端 `useDraftGuard` 组件存在但未接入 AnalysisWorkbench。 |
| 离开前 Save/Discard/Stay | **FAIL** | `useDraftGuard` 未接入任何页面。AnalysisWorkbench target/features 草稿离开无保护。 |
| experiment 切换彻底隔离 scientific context | **PASS** | `workflowContextKey(b, e)` 含 battery+experiment；`AssistantProvider key={b/e}`；`main` key remount。测试 W20 验证 key 隔离。后端测试 EXPT 验证 CELL_210 无泄漏。 |
| WAITING 在 Overview/Workspace/Assistant/Stepper 一致可见 | **PASS** | `WaitingBanner` 在 `WorkbenchShell` 全局渲染（所有页面可见）；Assistant drawer 内 `pending_user_action` 同步显示。 |
| BRW-018R2 same-run resume 后全局刷新 | **PARTIAL** | `useInvalidateWorkflow()` 提供统一 invalidate；但 `submission.ts` 是否调用它需 R3 验证。后端 `recommended_next_action` 正确反映 pending submissions。 |
| stale Dataset/Model/Report 依赖链可见 | **PARTIAL** | Stepper 显示 STALE 色（amber）；后端 `artifact_freshness` 正确计算 stale chain（测试 W21 验证）。但 Dataset/Model/Report 页面本身无 stale banner。 |
| Assistant 使用同一 next action 并返回 typed navigation action | **PASS** | `TYPED_NAV_MAP` 映射 11 个 action_id → step → route；typed actions 直接 navigate。后端 `typed_actions` 提供 action_id + route。测试 W26 验证 typed_actions 结构。 |
| navigation 本身零 science recomputation / 零 artifact write | **PASS** | 后端 `meta.read_only: true, no_recomputation: true`；测试 W28 snapshot 验证两次调用不修改任何 artifact。前端 stepper 仅 `navigate()`。 |
| localStorage 不作为 source of truth | **PASS** | 全局 grep 零命中。所有状态在后端 artifacts 或 react-query cache。 |

### 测试覆盖

| 测试 | 状态 | 覆盖 |
|------|------|------|
| 后端 W02 DTO schema | **PASS** | `test_workflow_context.py:63-86` |
| 后端 W04 current step | **PASS** | `test_workflow_context.py:88-100` |
| 后端 W05 step status + blocking | **PASS** | `test_workflow_context.py:88-110` |
| 后端 W10 dataset committed | **PASS** | `test_workflow_context.py:112-119` |
| 后端 W11 split bound to dataset | **PASS** | `test_workflow_context.py:121-127` |
| 后端 W12 models grouped | **PASS** | `test_workflow_context.py:129-135` |
| 后端 W13 report latest | **PASS** | `test_workflow_context.py:137-142` |
| 后端 W21 stale chain | **PASS** | `test_workflow_context.py:144-152` |
| 后端 W22 waiting global | **PASS** | `test_workflow_context.py:154-162` |
| 后端 W24 impossible split | **PASS** | `test_workflow_context.py:164-204` |
| 后端 W26 typed navigation | **PASS** | `test_workflow_context.py:206-218` |
| 后端 W27 assistant context | **PASS** | `test_workflow_context.py:220-225` |
| 后端 W28 no artifact writes | **PASS** | `test_workflow_context.py:227-247` |
| 后端 404 unknown experiment | **PASS** | `test_workflow_context.py:249-254` |
| 后端 EXPT experiment isolation | **PASS** | `test_workflow_context.py:258-268` |
| 前端 W02 client method | **PASS** | `workflow-context.test.tsx:103-108` |
| 前端 W04 current step derivation | **PASS** | `workflow-context.test.tsx:110-133` |
| 前端 W05 seven visual states | **PASS** | `workflow-context.test.tsx:135-171` |
| 前端 W08 Resume Research | **PASS** | `workflow-context.test.tsx:174-183` |
| 前端 W13/W17 prerequisite panel | **PASS** | `workflow-context.test.tsx:218-236` |
| 前端 W18 no POST on navigation | **PASS** | `workflow-context.test.tsx:238-251` |
| 前端 W20 experiment isolation | **PASS** | `workflow-context.test.tsx:253-262` |
| 前端 W22 WAITING banner | **PASS** | `workflow-context.test.tsx:185-216` |
| 前端 W26 typed actions | **PASS** | `workflow-context.test.tsx:264-276` |
| 前端 W02 CLIENT_PATHS | **PASS** | `workflow-context.test.tsx:278-285` |
| E2E 1–10 | **NOT STARTED** | 无 E2E 测试文件 |
| W01–W31 完整单元 | **PARTIAL** | 已覆盖 W02/W04/W05/W08/W13/W17/W18/W20/W22/W26；缺 W01/W03/W06/W07/W09/W11/W12/W14/W15/W16/W19/W21/W23/W25/W27–W31 |

### 截图

| 截图 | 状态 |
|------|------|
| 16 张真实截图 | **NOT STARTED** | 无 screenshot 脚本 |

---

## R3 必须完成的工作

### 高优先级（阻塞完成标准）

1. **接线 `useDraftGuard` 到 AnalysisWorkbench**
   - 文件：`AnalysisWorkbench.tsx`
   - 动作：在 target/features selection 变化时 `setDirty(true)`；导航时触发 Save/Discard/Stay 对话框
   - 验收：E2E7 unsaved draft guard

2. **接线 `PrerequisitePanel` 到深链路由**
   - 文件：`WorkbenchShell.tsx` 或各子页面
   - 动作：当 workflow-context 显示当前深链步骤为 BLOCKED/NOT_STARTED 时，渲染 PrerequisitePanel 替代默认内容
   - 验收：E2E3 deep link prerequisite

3. **修复 `/advanced/splits` 断链**
   - 文件：`AnalysisWorkbench.tsx:129,160`
   - 动作：改为 `/experiments/${batteryId}/${experimentId}/advanced/dataset-split` 或 stepper SPLIT 路由
   - 验收：E2E1 happy path 无 404

4. **Dataset build 成功后调用 `invalidateWorkflow()`**
   - 文件：`AnalysisWorkbench.tsx:152` `onBuilt` 回调
   - 动作：调用 `useInvalidateWorkflow()` 刷新 workflow-context + research-overview + assistant-session
   - 验收：E2E5 same-run resume 全局刷新

5. **Stale banner 在 Dataset/Model/Report 页面**
   - 文件：`ModelsWorkbench.tsx`、`ReportWorkbench.tsx`、`AdvancedPage.tsx`（dataset-split section）
   - 动作：当 `artifact_freshness` 为 STALE/LEGACY 时显示 banner
   - 验收：E2E4 stale chain visible

### 中优先级（完善覆盖）

6. **补充 W01–W31 缺失单元测试**
   - 至少覆盖：W01(路由表)、W03(canonical 8 步顺序)、W06(target 继承)、W07(features→preview)、W09(preview→dataset)、W11(split→model)、W12(model→report)、W14(deep link recovery)、W15(back/forward no POST)、W16(experiment switch refresh)、W19(assistant typed nav click)、W21(stale chain UI)、W23(WAITING banner consistency)、W25(draft guard reducer)、W27–W31(remaining)

7. **E2E 测试 1–10**
   - E2E1 happy path full chain
   - E2E2 Back/Forward no POST
   - E2E3 deep link prerequisite
   - E2E4 stale chain visible
   - E2E5 WAITING sampling-rate resume
   - E2E6 impossible split BLOCKED
   - E2E7 unsaved draft guard
   - E2E8 experiment switch isolation
   - E2E9 assistant typed navigation
   - E2E10 navigation artifact immutability

8. **16 张真实截图**
   - 需 `screenshot-brw025wf.mjs` 脚本
   - 基于 CELL_001/EXP_001 demo 数据
   - viewport 1440x900

### 低优先级（不阻塞完成标准）

9. 移除或重定向 `overview-classic` 幽灵路由
10. 统一 `research_overview.py _next_actions()` 与 `workflow_context.py recommended_next_action`（消除 G1 残留）
11. Models 空态 split 指引修复（G11）

---

## 结论

R2 建立了完整的 ScientificWorkflowContext 基础设施（后端 read model + 前端 hook + stepper + WaitingBanner + typed navigation），闭合了 R1 的 G5/G9/G13 三项高优差距。但仍有 4 项关键接线工作未完成（draft guard、prerequisite panel、stale banners、dataset build invalidation），2 项断链未修复，E2E 测试和截图未开始。

**当前评估**：基础设施 PASS，接线 FAIL，测试 PARTIAL，视觉 NOT STARTED。

**R3 完成后预期**：全部 master prompt 完成标准可达。
