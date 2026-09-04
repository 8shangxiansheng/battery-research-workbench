# BRW-025 SCIENTIFIC WORKBENCH UI REPORT

## Architecture

```
React 18 + TypeScript + Vite (frontend/)
  → typed client (src/api/client.ts, 契约 = docs/api/openapi-v1.json)
  → TanStack Query (server state) + React Router (URL state)
  → BRW-024 /api/v1 only
  → WorkbenchService → Orchestrator / domain services → scientific core
```

UI 无任何 parquet/manifest/zarr 访问；无科学计算；无 tuning UI；无 Agent。

## Frontend Stack

React 18.3 + react-router-dom 7 + @tanstack/react-query 5 + Vite 7 + Vitest 4 +
Testing Library + typescript-eslint（strict, noUncheckedIndexedAccess）。图表为受控 SVG 自绘。

## API Contract

typed client 覆盖 41 path/method 组合；`tests/client-contract.test.ts` 做 OpenAPI drift
检查（快照变化而 client 未更新 → fail）。后端新增 2 只读端点并更新快照：
- `GET /experiments/{b}/{e}/waveform-frames`（帧元数据清单）
- `GET /experiments/{b}/{e}/waveform-frames/{frame_index}?max_points≤1000`（降采样 preview, x_axis=SAMPLE_INDEX）
- `GET /runs`（run 列表，只读枚举）

## Page Inventory（9 页面，简体中文 + 中英术语）

工作区 / 波形与闸门 / 特征 / 特征分析 / 数据集与划分 / SOC建模 / 科学报告 / 证据与血缘 / 运行记录。

## Workspace

只用 workspace-summary；readiness/limitations/next_actions 原文展示（TOF BLOCKED、
SOH NOT_READY、PROVISIONAL、READY_FOR_LIMITED_EVALUATION），UI 不推导。

## Waveform & Gates

帧选择（0..3998）→ API preview（≤1000 点降采样）；无验证 fs → x 轴固定 Sample Index、
time_axis_us=null（T07/T08 断言无 μs 轴）。SVG 拖选 draft gate（橙色）→ 填名 → POST /gates
→ committed（蓝色）+ gate_id 绑定（T09-T11）。UI 无任何特征计算控件（T12）。

## Scientific Actions

WAITING_FOR_USER → action 面板显示 action_type/message/scientific_reason/required_fields；
MISSING_SAMPLING_RATE 提供 数值+单位(Hz/kHz/MHz) 输入，客户端只做纯单位换算成 Hz 提交；
不猜值、不用 frame cadence 冒充；提交 → POST user-actions → resume → 状态刷新（轮询）。
API 拒绝时显示 SCIENTIFIC_ACTION_REQUIRED 面板 + request_id（T17），非 generic error。

## Features

CORE 区块（tof_us/amplitude_a_u）优先；DERIVED(wave_speed) 独立；AUXILIARY 折叠（details）。
TOF: NOT_AVAILABLE_CURRENT_ENVIRONMENT + 原因（null 语义）。勾选 = draft FeatureLocator，
不自动 POST（T23）。

## Feature Analysis

两种模式显式 radio 区分；EXPLORATORY 显示 "not ML-safe for unbiased selection" 横幅（T25）；
ML-safe 显示 "HELD_OUT 组标签不参与 selection"（T26/T27）。相关性表列全（Feature/Gate/Pearson/
Spearman/N/Missing/Scope/Status）且标注 "按 |Spearman| 排序（不自动命名 Best Feature）"；
数据来自 API，前端不重算（T28）。redundancy/子组 filter 区域遵循 API-first 原则（无数据不伪造）。

## Dataset & Split

显式勾选特征 → POST /datasets（REUSED 幂等）→ POST /splits → 显示
group_column=cycle_group_id + require_roles=["TRAIN","HELD_OUT"]；blocked 特征不可选、
不可用特征明确不列为 predictor（T33 语义）；2 独立组 3-way 不可行时 API 返回
SCIENTIFIC_ACTION_REQUIRED（行动面板），无 random row fallback。

## Modeling

5 策略（Dummy Mean 高亮为基线）+ per-fold MAE/RMSE/R2 表 + macro 表 + vs-Dummy 差值列。
真实结果未优于 Dummy 时显示诚实横幅："工程评估已完成（evaluation complete），预测优势未被证明
（predictive advantage not demonstrated）"，非 "Model Failed"（T40）。方向性指标 API 未提供时
如实标注"API 未提供"，不前端重算。无 tuning 控件（T42）。

## Reports / Evidence & Lineage

POST /reports 幂等（REUSED），列表 + 状态；证据表按 EvidenceType 视觉区分
（直接当前产物=绿 / 既往审计=橙 / 源代码推断=紫）；11 limitations drill-down；
lineage stepper 显示 artifact_id + AVAILABLE/NOT_AVAILABLE 状态。

## Runs

列表 + 状态（REUSED/EXECUTED/BLOCKED/WAITING_FOR_USER 中文标签）+ 5s 轮询；
详情 + pending actions + 端到端 action/resume 流（T13-T18）。

## Error UX

6 类面板（scientific-action / readiness-blocked / artifact-unavailable / validation /
integrity / internal），internal 只显示 request_id，不显示 traceback（T17 断言）。

## Accessibility

label 绑定全部输入；键盘拖选 fallback（Enter 提交 draft）；role="status"/"alert" 状态文字；
SVG 有 aria-label + 表格 fallback；颜色对比满足常规文本（浅底深字）。

## E2E

`frontend/tests/e2e-happy-path.test.ts`：起真实 uvicorn（battery_workbench.api.serve:app,
真实 CELL_001/EXP_001）→ workspace(3999 frames, READY_FOR_LIMITED_EVALUATION) → waveform
→ features(TOF unavailable) → modeling(5 macro) → evidence → lineage → POST /reports 幂等
REUSED。✅ 1 passed。全部写操作只经幂等确定性路径，真实数据零污染（git 干净）。

## Real Artifact Demo

真实 CELL_001/EXP_001 API artifacts 全链实测通过（见 E2E）。可用性：waveform frames=3999、
40 results、7 evidence、11 limitations、5 macro strategies。

## Scientific Invariants

TOF blocked→null+reason（无 0 μs）；SOC=RETROSPECTIVE derived；HELD_OUT 不参与 selection；
HELD_OUT 语义（非 VALIDATION）；无 tuning；弱结果诚实；Best Feature 不自动命名；证据等级不升级。

## Input Integrity

`git status data/raw data/processed` = 空；BRW-003–024 artifacts 未改变；
后端改动仅为 additive（2 只读端点 + runs list + ReportSpec 可选参数向后兼容）。

## Tests / Build

- 后端全量: 855 passed / 2 skipped（含 74 API tests + 6 waveform tests）
- 前端: 31 passed + 1 E2E passed（vitest, jsdom）
- eslint: 0 errors；tsc --noEmit: 0 errors；vite build: 成功
- git diff --check: clean

## Final Answers（§77）

1. Can user complete workflow without manual file reading? **YES**
2. Does UI use only public API? **YES**
3. Can user inspect waveform/create gates? **YES**
4. Can missing scientific parameters be resolved? **YES**
5. Does blocked TOF remain null/blocked? **YES**
6. Can user flexibly select features? **YES**
7. Are exploratory/ML-safe modes distinct? **YES**
8. Can grouped splits be inspected? **YES**
9. Are weak model results honest? **YES**
10. Can evidence/limitations/lineage be inspected? **YES**
11. Does WAITING_FOR_USER work end-to-end? **YES**
12. Do read pages avoid recomputation? **YES**
13. Are scientific artifacts unchanged? **YES**

全部核心项 YES → BRW-025 COMPLETE。停止，不进入 BRW-026 Agent。
