# BRW-025R SCIENTIFIC WORKBENCH UI V2 REPORT

## Reference UX Review

| Product | Pattern | Why it works | Our adaptation | Reuse/Adapt/Reject | Where used |
|---|---|---|---|---|---|
| FiftyOne | 分步 import 向导 + 进度/错误面板 | 复杂 intake 拆成可回退小决策 | 6 步 Wizard，server session 可恢复 | Adapt | Wizard |
| MLflow | Library 首页 + detail 摘要卡 + run 两级 + 折叠 tags | 首页即工作清单，ID 收进折叠 | Experiment Library / Detail / Runs | Adapt | 首页/详情/运行 |
| Kedro-Viz | 渐进披露 + lineage 下钻 | 概览→细节层次 | Pipeline Stepper / context panel | Adapt | 详情/血缘/波形 |

## V1 → V2 Migration

首页 Workspace→Library；9 平铺菜单→7 生命周期分组；ID dump→摘要卡+Advanced 折叠；
新增 Data workspace；Wizard 全新增；typed client 42→61 paths；正式 Design System。

## Design System

tokens.ts（§20 色板）+ components.tsx（Card/Badge/Stepper/Collapse/Drawer/EmptyState/StatusText）；
CSS 变量注入全局；ID monospace、正文 sans；radius 6-8px。

## Experiment Library

首屏 Library：搜索（名称/ID）、状态过滤、is_demo 过滤、分页（limit/cursor）；
每行 name/composite/status/asset 数/Demo badge/updated_at；
[+ 新建实验] [加载 Demo]；空态=欢迎+[创建第一个实验][加载 Demo]。

## New Experiment Wizard

6 步 Info→Assets→Detection→Preview/Validation→Metadata→Commit/Start；
Back/Continue/Cancel；sessionId 在 URL 刷新可恢复；Info 支持自动 ID；
Assets 分区上传（progress/sha256/status）；Detection 三态 + AMBIGUOUS 面板（必须人工选）+
UNSUPPORTED 面板（含支持能力）；Validation 三维度分表 + fs UNKNOWN ⚠ 不阻断；
Commit 前 summary → 确认导入 → Raw registered/Checksums verified/READY_FOR_PIPELINE →
明确点击 [开始数据处理]（走 BRW-019）或 [稍后]。

## Intake / Adapter Detection / Preview / Validation

全部走 BRW-024R intake API；detection 展示 adapter_id/version/reason/signature；
preview 展示 electrical sheets+rows / ultrasound frames+samples+cadence；
三维度验证结果逐条渲染；cadence 标注"不是 sampling rate"。

## Scientific Metadata

突出 sampling rate；advanced（trigger/time-zero/path length 等）折叠；
"稍后提供"→ 注明 TOF 将暂不可用；fs unknown 保持 UNKNOWN。

## Commit / Pipeline Start

用户明确点击开始；RUN_INGEST_TO_MEASUREMENT_EVENTS 为 recommended_next_action 默认。

## Experiment Detail

Header(name/battery/experiment/status) + Pipeline Stepper(11 步) + Data Summary +
Readiness + Limitations top-4 全部折叠 + next-action 按钮卡 + Latest Results
（含 Dummy 对比与诚实弱结果横幅）+ Advanced(artifact IDs) 折叠。

## Data Quality / Sync

Assets 表(role/adapter/短 checksum/filename)；Quality(records/cycles/steps/重复时间戳；
frames/cadence/fs UNKNOWN)；Sync(match_state/ambiguous/tolerance/validated_sync/
PROVISIONAL 时间基)；Events 分页预览(20/页, next cursor)。

## Waveform / Gates

保留 V1 大波形 + drag-select draft gate + committed overlay + SAMPLE_INDEX 轴（无 fs）。

## Features / Analysis / Dataset / Modeling / Reports / Runs

V1 语义全部保留并挂入新 IA：CORE 优先/AUX 折叠/TOF blocked；
Exploratory/ML-safe 横幅；不重算；grouped TRAIN/HELD_OUT；
Dummy 基线+诚实弱结果；报告 REUSED；证据分级；WAITING_FOR_USER 抽屉。

## Accessibility

键盘焦点可见、label 绑定、role=status/alert、file picker 等价于拖拽、表格 fallback。

## E2E A — Demo（真实 CELL_001/EXP_001）

v2-api-contracts.test.ts（sandbox uvicorn + BRW_SANDBOX 隔离）:
library 列出 demo（is_demo=true）→ data-quality(3999 frames, fs UNKNOWN) →
sync(validated_sync=false, PROVISIONAL) → events 分页 → results。

## E2E B — Brand-new Experiment（无 Demo 起点验证）

backend 验收脚本（tmp workspace, 空 manifests, 无 CELL_001/EXP_001）:
library 空 → load-demo 404（demo 确实不存在）→ create CELL_300（无 demo 参照）
→ intake upload → detect 双 UNIQUE → validate(fs UNKNOWN) → commit →
run SUCCEEDED → MeasurementEvents parquet 落盘。
精确 demo 指纹扫描（CELL_001/2024-01-06/09:52:31/E001/U001/LB::/PS::/FS::/GATESET::/
DS::/SPLIT::/REPORT::/MODEL::）→ **零命中**。
frontend E2E B：create→upload→detect→validate→commit→start pipeline（sandbox uvicorn）✓。

## API Boundary

新增 4 个 minimal additive 端点：data-quality / synchronization /
measurement-events(分页只读) / load-demo(lifecycle-only, 幂等)。
OpenAPI 55 paths 快照更新；BRW-025 drift 测试同步；无科学算法改动。
UI 零 parquet/manifest 直接访问。

## Input Integrity

发现并修复一处测试污染风险：v2 contract tests 曾以真实 workdir 启动 uvicorn，
现强制 BRW_SANDBOX_RAW/PROCESSED 环境变量 + serve_sandbox.py 无环境变量拒绝启动。
真实 data/raw+processed 在测试前后 git status 零改动（本轮已把一次意外污染还原）。

## Tests / Build

- 后端：905 passed / 2 skipped（+5 data-v2 tests）
- 前端：38 passed + 1 conditional skip（含 E2E A/B 契约）；eslint 0；tsc 0；build ✓
- git diff --check clean

## Final Answers（§41）

1. Is CELL_001/EXP_001 now only a demo entry? **YES**
2. Can a user create a brand-new experiment entirely through UI? **YES**
3. Can electrical/ultrasound data be imported without manual raw-folder work? **YES**
4. Can adapter detection/ambiguity be handled interactively? **YES**
5. Can users preview and validate before commit? **YES**
6. Are unknown scientific parameters preserved? **YES**
7. Can the user start the scientific pipeline after import? **YES**
8. Can users inspect data quality/synchronization? **YES**
9. Can users inspect waveforms/create gates? **YES**
10. Can users flexibly analyze/select features? **YES**
11. Can users inspect grouped split/model/report/evidence? **YES**
12. Does UI avoid recomputing canonical science in browser? **YES**
13. Does V2 remain usable if original Demo is removed? **YES**（E2E B 零 demo 起点 + 零指纹泄漏）
14. Are existing Demo artifacts unchanged? **YES**

全部核心项 YES → BRW-025R COMPLETE。停止，不进入 BRW-026。
