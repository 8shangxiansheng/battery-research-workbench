# 科学扩展能力与数据就绪状态

本文件记录扩展能力的**当前实现状态**与**真实数据激活条件**。查看状态时要区分：API/算法是否已实现、当前数据是否满足条件、是否已有真实科学验证。接口存在或合成测试通过，不等于当前实验已获得相应科学证据。

统一的只读 readiness 接口为：

```http
GET /api/v1/experiments/{battery_id}/{experiment_id}/extension-readiness
```

响应包含观测到的电池/队列/标签/温度/时间基准信息、能力边界状态，以及版本化 contract descriptor。常见状态为 `BLOCKED_BY_DATA`、`BLOCKED_BY_VALIDATION`、`NOT_IMPLEMENTED`、`PARTIALLY_READY` 和 `READY`。

## 当前能力状态

| 能力 / Contract | 当前实现 | 当前数据门与限制 |
|---|---|---|
| `cohort-dataset/1.0` | 已实现并启用；支持创建/读取不可变 harmonized SOC cohort，以及 Battery-grouped LOBO evaluation | 至少 2 个声明 Battery ID；每个 Battery 可纳入多个不同 Experiment 的 source Dataset，同一 Battery/Experiment pair 与 source Dataset ID 不可重复；来源 dataset、标签公式/temporality、特征定义和单位须兼容且通过 checksum 验证。LOBO 仍以 Battery 为整体分组，不能把同一 Battery 的多个 Experiment 当作独立外层组。当前 Battery 物理身份仍为 `NOT_ASSESSED`，CELL_001 本身不满足跨电池证据门 |
| `timebase-validation/1.1` | 提案、列表/读取、审核、拒绝/撤销 API 及 Alignment 页面入口已实现；独立只读 `timebase-evidence-preflight/1.0` 会对 raw-root-relative 路径计算 hash/size 并供 UI 自动填入来源 checksum；创建/接受时仍会重新核对路径边界、存在性和 SHA-256，审计记录文件 hash/size；接受的提案须显式触发重算，才会作为指定 run 的 provisional anchor override | 文件字节完整性核验不代表证据科学充分，也不验证操作者身份；误差、时区与无歧义仍是操作者声明，尚无文件上传/认证审核身份；接受/重算均不会自动设 `validated_sync=true`。真实 CELL_001 时间基准仍为 `PROVISIONAL` |
| `target-dataset/1.0` | 通用写入 endpoint 尚未实现；readiness descriptor 暴露严格的目标标签 provenance request schema；另有只读 source-evidence preflight，可按 Battery/Experiment/DataAsset 身份、raw checksum，并在 parser manifest 存在时再核对 parser checksum/路径；响应 OpenAPI schema 固定 `NOT_ASSESSED` 与 `materialization_enabled=false` 边界；接口不评估标签语义、目标 readiness 或 feature availability；现有 Targets API 同时返回 label/MeasurementEvent/parser manifest 中可追溯的公式/测量方法、版本、粒度、来源文件/checksum 和 uncertainty 状态；已有 Reference SOC 工作流、温度目标数据门及 cycle-level SOH 标签构建/校验能力 | schema 要求 target ID、语义类型、单位与 grain 相符，显式给出公式/测量方法、方法版本、manifest-backed 来源引用/checksum、uncertainty 为量化或带理由的 UNKNOWN，并声明 Battery 独立外层单位。Battery 与 Experiment ID 按位置一一配对且 pair 唯一；feature locator 使用严格的 `feature_name` + 可选 `gate_id`，并拒绝重复 locator，以保留同一特征跨窗口身份。`minimum_independent_states` 仅允许 SOH target 使用且必须显式提供；SOC/温度不得携带该字段。温度另需实测通道、覆盖审计、位置/校准验证；SOH 仍要求独立 cycle 状态与参考容量来源。当前 CELL_001 的温度位置/校准未验证，SOH 仍仅 2 个独立状态；schema/API 有 provenance 不代表标签验证通过 |
| `tuning-study/1.0` | 请求 schema/readiness descriptor 已有；`POST /api/v1/tuning-studies` 尚未实现 | 需要独立 `VALIDATION`、未触碰的 `HELD_OUT` 和嵌套分组选择。当前无独立验证角色，固定基线不等于调参 |
| Dummy 优势评估 | 固定基线模型比较已实现，策略来自 `/api/v1/modeling/strategies` | 是否超过 Dummy 是结果，不是接口启用门；需结合当前 dataset、split 和评估范围解释 |

## Cohort / LOBO 已实现路径

- `POST/GET /api/v1/cohort-datasets` 和 `GET /api/v1/cohort-datasets/{cohort_dataset_id}` 管理 manifest-backed、不可变的 harmonized SOC cohort。
- `POST /api/v1/cohort-datasets/{cohort_dataset_id}/lobo-evaluations` 按 `battery_id` 留一电池评估；训练视图不含 held-out 电池标签。`GET /api/v1/cohort-lobo-evaluations/{evaluation_id}` 读取结果。
- V1 只接收满足契约的 Reference SOC 数据集；标签定义和特征定义须兼容，单位必须完全匹配，不执行单位转换。
- 输入 manifest、Parquet 与特征定义 checksum 被追踪。源数据变化后 cohort 会变为 stale，不能作为新评估的有效输入。
- 一个 cohort 可包含同一声明 Battery 下多个 Experiment 的 source Dataset；物化后的事件 ID 会纳入 Battery、Experiment、source Dataset 与源事件 ID，避免不同 Experiment 复用源事件键时碰撞。Battery 是 LOBO 外层分组，因此同一 Battery 的全部 Experiment 必须留在同一 fold/role。
- 主要汇总指标为各 held-out 电池等权宏平均；pooled-row 指标仅为诊断项。合成数据测试验证接口和泄漏边界，不构成真实跨电池泛化证据。
- 当前真实 CELL_001 / EXP_001 是单电池样例。跨电池 readiness 必须在至少 2 个独立电池进入兼容 cohort 并通过来源校验后才可能开放。

## 科学边界

- 跨电池泛化使用 `battery_id` 作为外层分组；禁止用随机帧、行、MeasurementEvent 或 SOC 分箱切分代替。
- SOH 的独立样本单位是 cycle/battery 级状态，不能把帧行计作独立健康状态。现有标签构建/离线复用校验不等于 SOH 建模就绪。
- SOH 建模已实现并按去重参考值门控：`SOC_MODELING` 节点接受 `soh_capacity_reference_percent`，要求至少 3 个去重 SOH 参考值（与 FeatureAnalysis 门同一口径），否则以 `SOH_MODELING_NOT_READY` 阻断；评估按 cycle 级独立状态分组（`independent_soh_group_id`）做 leave-one-group-out，事件行不重复计权，SOC 专属分箱诊断不应用于 SOH。该阈值是最低要求而非充分证据：真实跨状态结论仍需更多老化 cycle 与独立电池。
- 关系分析的稳健性统计（P4 部分）：特征分析现给出相关系数置信区间（默认 Fisher-z 解析，bootstrap 需显式开启并带固定种子）、跨“特征 × 方法”族的 Benjamini-Hochberg FDR 校正（保留未校正值对照），以及伪重复诊断（名义行数 vs 独立单位数与复制倍数）和 pooled / 组间 / 组内三者分离（`GROUP_AND_WITHIN_DISAGREE` 暴露 Simpson 型方向冲突）。这些是**探索性**统计：不把相关写成因果，不构成确认性结论，也不能替代预声明方案、混杂调整或独立验证数据；区间无法计算时返回空值而不是伪造边界。
- 温度只能来自实测通道；当前 target gate 还要求覆盖审计、至少 2 °C 观测范围及传感器位置/校准验证证据。CELL_001 的 T1 auxTemp 已按 `(electrical_asset_id, record_index_raw)` 关联，但尚无位置/校准证据，因此保持 `BLOCKED_BY_VALIDATION`。不得从超声或其他特征推算温度标签。
- 调参若实现，特征选择与搜索须局限于训练数据中的独立分组验证角色；外层 held-out 标签不得参与选择。
- 不能超过 Dummy 是诚实的科学结果，不是软件故障。增加更复杂的固定模型不构成调参，也不能弥补独立电池或验证数据缺失。
- `READY` 只表示对应 readiness 条件通过，不自动等于生产级证据或普适科学结论。

可执行 contract 定义位于 `src/battery_workbench/api/future_contracts.py`；cohort 请求 schema 位于 `src/battery_workbench/datasets/cohort_schemas.py`。变更 API 状态时应同步此表、API 文档、测试与真实数据证据。
