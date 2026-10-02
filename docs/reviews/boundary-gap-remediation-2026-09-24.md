# 能力边界与 UI/工作流缺口 —— 完善计划

日期：2026-09-24。范围：回应"这些缺口怎么完善"。逐项给出：当前证据 → 缺口的真实性质（数据受限 vs 代码受限）→ 完善路径 → 验收标准。本轮同时落地了三个代码可闭环的 UI/工作流缺口（见 B 节）。

`GET /api/v1/experiments/{b}/{e}/extension-readiness` 是本节论断的机器可读来源；
当前真实链路观测：`battery_count=1, timebase=PROVISIONAL, independent_soh_states=2,
temperature_valid_count=0, has_independent_validation=false`。

## A. 科学证据边界（数据受限 —— 不能用代码"修掉"，只能准备到"数据一到即可激活"）

### A1. 数据规模有限 / 跨电池泛化证据不足
- 性质：单电池（CELL_001）、2 个循环组。任何调参或换模型都不会制造第二块电池。
- 完善路径：
  1. **数据**：用现有 intake 生命周期接入第 2+ 块电池（多资产导入链已可用，`NewExperimentWizard` 支持 file_start_time 来源标注）。
  2. **协议**：跨电池评估必须 `battery_id` 作外层分组（leave-one-battery-out）；契约已写入
     `cohort-dataset/1.0`（docs/architecture/future-scientific-extension-contracts.md），激活门 = ≥2 独立电池 + 特征/目标定义对齐。
  3. **代码可先行**：在合成双电池 fixture 上实现并测试 LOBO 拆分与聚合宏平均（确定性模块，非 Agent 提示），readiness 端点保持 `BLOCKED_BY_DATA` 直到真实第 2 块电池到位——实现先行不等于能力开启。
- 验收：合成 fixture 的 LOBO 单测通过；真实链路报告仍只声明 WITHIN_BATTERY 范围；readiness 状态在真实双电池出现前不得翻绿。

### A2. 超参数调优
- 性质：不是"没写调参器"，是没有合法评估它的验证角色（无独立 VALIDATION 组）。在没有留出验证集时调参=在训练集上自我打分。
- 完善路径：`tuning-study/1.0` 契约已休眠待装；实施顺序 = ①嵌套分组选择模块（内层 TRAIN-only CV）→ ②readiness 门检查 `has_independent_validation` → ③通过后才挂 `POST /tuning-studies`。任何 tuning 运行不得读外层 HELD_OUT 目标。
- 验收：调参候选选择在折叠内完成的结构测试；HELD_OUT 目标在 tuner 代码路径不可达（签名级隔离，与 BRW-022 fit_model 同一手法）；UI 的"暂不支持调参"入口保持诚实直至门通过。

### A3. 温度通道
- 性质：真实 events 有 `temperature_c` 列但有效读数=0、无观测方差 → 无信息通道。目标定义 `temperature_c` 已在 targets 列表中存在（定义 ≠ 可建模）。
- 完善路径：①采集端保证温度与电学同资产时间对齐入库；②readiness 的 `TEMPERATURE_MODELING` 需要 measured>0、覆盖率审计与真实方差才翻 `PARTIALLY_READY`；③届时尚无特征-温度混杂控制前，温度只作诊断维度不作预测目标。
- 验收：覆盖率/方差阈值全部由 `extension-readiness` 观测值驱动，禁止手工置 READY；UI 已按温度可用性分支（Analysis 关系视图已实现该分支）。

### A4. 独立 SOH 状态能力
- 性质：当前仅 2 个独立健康状态；契约规定帧行不算独立状态（3999 行 ≠ 3999 个电池）。目标 `soh_capacity_reference_percent` 已在 API 报告 `NOT_READY_INSUFFICIENT_SOH_STATES`（test_api_resources 断言在案）。
- 完善路径：`target-dataset/1.0` 激活门 = ≥3 独立 SOH 状态 + cycle/battery 级目标粒度 + 参考容量来源；数据侧需要带标定容量记录的独立循环/电池。
- 验收：SOH 建模入口只在 readiness 翻绿后出现；报告永远携带"独立状态数"这一限制。

## B. 本轮已闭环的 UI/工作流缺口（2026-09-24）

### B1. 标定参数持久化（原审查：调整后的 gates 不随冻结提交）
- 已落地：`freeze_gate_calibration` 接受并校验 `gate_bounds`（未知模板/非法区间 400）；
  边界进入记录指纹 → 相同重提交幂等 REUSED，修改边界生成新的不可变 GC 记录；
  `resolve_gate_calibration` 读回最新 FROZEN 记录；GET gate-calibration 将冻结边界覆盖进
  `gate_templates` 并标注 `bounds_source=EXPERIMENT_FROZEN`；CalibrationWorkbench 提交调整值、
  闸门 chip 显示"已冻结持久化"。顺带修复了包络开关两分支相同的死控件。
- 测试：tests/unit/test_gate_bounds_persistence.py（解析器）+ test_api_resources.py 两个 API 用例（含清理）。
- 遗留（属计算链改造，单列任务）：SWA 等模板驱动特征的**计算**目前仍读源模板；让
  physical_v2/gated-features 消费冻结边界会改变特征值 → 需 golden/parity 测试与整链重算
  （合同 §12/§13），不在本轮顺手做。

### B2. 跨资产电学上下文（原审查：WaveformWorkbench 固定前 50 事件）
- 已落地：`GET /measurement-events` 增加 `frame_index`/`asset_id` 过滤，DTO 暴露
  `sync_error_s、provisional_absolute_timestamp、match_status、anchor_status、
  ultrasound_asset_id、electrical_asset_id、electrical_timestamp`（合同 §8：对齐不确定性不得隐藏）；
  WaveformWorkbench 按当前帧取事件，顶栏显示 同步 ±0.031 s · 超声 U001 · 电学 E001（浏览器已验证）。
- 测试：test_measurement_events_frame_scoped_with_sync_provenance + redesign.test.tsx 帧作用域查询/芯片断言。

### B3. 部分特征身份匹配（原审查：`selected_features.some` 重叠即算 ML-safe）
- 已落地：AnalysisWorkbench 改为精确集合相等（`normFeatureSet`：去 gate 后缀、排序拼接），
  仍要求 split_id；部分重叠不再命中 ready-analysis。
- 测试：redesign.test.tsx 身份函数直测（相等/不等两组断言）。

## C. 昨日运行链路补记

- SOC_MODELING 假复用（pass-1/pass-2 时序洞）的回归测试 tests/unit/test_soc_modeling_reuse_guard.py
  随本轮提交（引擎 REUSE_REVALIDATED 修复已在 8a1dfd5 落地）。

## D. 优先级建议（执行顺序）

1. ~~B1/B2/B3~~（本轮完成）
2. **A1-③ LOBO 内核已完成（2026-09-27；仅确定性拆分与合成测试）**
3. A2-①：嵌套分组选择模块骨架 + 签名级 HELD_OUT 隔离
4. B1 遗留：冻结边界进入特征计算（golden 测试 + canonical 链重算，作为独立 BRW 任务排期）
5. 数据侧：第二块电池/带温度梯度实验/SOH 标定循环 —— 实验台账决定，不受代码影响

## E. LOBO 内核执行记录（2026-09-27）

- `SplitSpec` 对 `split_unit=BATTERY` 强制 `group_column=battery_id`；沿用现有
  deterministic `LEAVE_ONE_GROUP_OUT` 分组器，不新增随机或按行拆分策略。
- 新增 `macro_average_by_battery()`：每块电池一条 held-out 指标、等电池权重；
  pooled-row 诊断不属于该宏平均。
- 新增 `tests/unit/test_battery_lobo.py`，使用 3 块合成电池、多个实验/循环和不等行数，
  覆盖 fold 原子性、行顺序/目标值独立、单电池不可行、空/重复身份和等权聚合。
- 验证集：LOBO、既有 cycle split、modeling、persistence、extension-readiness
  单元/集成测试通过；Ruff check 与 `git diff --check` 通过。
- 上述记录是 Phase A 完成时状态；Phase B 已在 2026-09-27 接入，详见下节。真实 CELL_001
  的科学范围仍为 `WITHIN_BATTERY_CROSS_CYCLE`，跨电池 readiness 仍由真实兼容 cohort 数据门控。

## F. Cohort 端到端启用记录（2026-09-27）

- 新增严格 Cohort Dataset 请求契约：source dataset IDs、目标映射、特征映射、单位、方法/策略版本与 evidence refs 必填；禁止客户端路径。V1 仅支持 retrospective reference SOC，要求 source label 公式版本/temporality 完全一致；特征单位必须与 definitions sidecar 完全一致，暂不转换单位。
- `POST/GET /api/v1/cohort-datasets`：按服务端 manifest 解析数据，写入独立 `data/processed/cohorts/` namespace；source datasets 不被改写。事件 ID 在 cohort 内按 Battery 命名空间化，保留 source event ID。
- Cohort 身份由完整请求确定；source manifest、Parquet、feature definition checksum 被记录。source 变化时列表标 `STALE_SOURCE`、新评估被拒绝，需生成新 cohort version。
- `POST /api/v1/cohort-datasets/{id}/lobo-evaluations` 使用 `battery_id` 分组和已有 fixed baseline；fit 视图只含 TRAIN 电池的 target，held-out target 仅进入评分。持久化 per-battery 指标、等权 macro、单独标记的 pooled-row diagnostic、assignments、predictions 与 cohort JSON/HTML report。
- Models 页增加 cohort LOBO 区域；无包含当前实验且至少 2 块电池的有效 cohort 时明确阻断。合成 cohort API E2E 验证多电池折叠、来源、macro、报告与 stale invalidation；前端以正式 API client 读取/运行。
- Readiness 不再用全局注册 Battery 数量激活跨电池状态；只接受 source/Parquet checksum 验证通过、且包含当前实验的 cohort。当前 repository 没有第二块真实兼容电池的 processed dataset，因此真实 readiness 仍 `BLOCKED_BY_DATA`；synthetic success 不构成真实泛化证据。
- 限制：V1 不做单位换算、温度/SOH cohort、嵌套调参；生成了 cohort-specific fixed-baseline 报告，但尚未并入单实验报告列表或 Result Registry。旧 CELL_001 单实验模型/报告 contract 保持原样。

## G. 后续实现状态补记（截至 2026-10-02）

以下状态是对本计划后续提交的补记；A–F 各节保留其原始日期和当时结论，不作为当前功能清单单独引用。

- **Cohort / LOBO**：F 节所述 cohort API 与 Models 页面入口已在当前主线实现。能力已启用，但真实跨电池评估仍要求至少 2 个来源校验通过、定义兼容的独立电池数据集；当前 CELL_001 单电池不满足该门。
- **Temperature target**：由无条件拒绝调整为数据门控；只有存在实测有效温度且范围至少 2 °C 时才允许目标数据集。当前样例没有有效温度读数，仍不可建模。
- **SOH**：容量比标签公式和来源 provenance 有离线测试锁定；这不改变数据门。当前只有 2 个 cycle 级独立状态，至少需要 3 个状态才能满足 SOH 建模 readiness。
- **模型策略**：固定基线扩展为 11 种策略，新增 ElasticNet、Huber Regression 和 MLP Regressor；策略清单由 `GET /api/v1/modeling/strategies` 提供并可在 UI 选择。所有配置仍是预声明固定参数，不是超参数调优。
- **仍未闭合的数据/方法项**：时间基准验证写入流程、独立 VALIDATION 角色与嵌套分组调参仍未实现；新增模型策略也没有增加真实独立电池或验证数据。
