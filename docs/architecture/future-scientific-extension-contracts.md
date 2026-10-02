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
| `cohort-dataset/1.0` | 已实现并启用；支持创建/读取不可变 harmonized SOC cohort，以及 Battery-grouped LOBO evaluation | 至少 2 个独立电池；来源 dataset、标签公式/temporality、特征定义和单位须兼容且通过 checksum 验证。当前 CELL_001 数据本身不满足跨电池证据门 |
| `timebase-validation/1.0` | descriptor/readiness 已有；验证写入 endpoint 尚未实现 | 需要逐资产绝对时间锚点、时区、来源证据和误差审计。当前时间基准仍为 `PROVISIONAL` |
| `target-dataset/1.0` | 通用写入 endpoint 尚未实现；已有 Reference SOC 工作流、温度目标数据门及 cycle-level SOH 标签构建/校验能力 | 温度需有实测通道、覆盖审计且观测范围至少 2 °C；SOH 建模要求至少 3 个独立状态、cycle/battery 粒度及参考容量来源。当前样例无有效温度读数且仅 2 个独立 SOH 状态 |
| `tuning-study/1.0` | 请求 schema/readiness descriptor 已有；`POST /api/v1/tuning-studies` 尚未实现 | 需要独立 `VALIDATION`、未触碰的 `HELD_OUT` 和嵌套分组选择。当前无独立验证角色，固定基线不等于调参 |
| Dummy 优势评估 | 固定基线模型比较已实现，策略来自 `/api/v1/modeling/strategies` | 是否超过 Dummy 是结果，不是接口启用门；需结合当前 dataset、split 和评估范围解释 |

## Cohort / LOBO 已实现路径

- `POST/GET /api/v1/cohort-datasets` 和 `GET /api/v1/cohort-datasets/{cohort_dataset_id}` 管理 manifest-backed、不可变的 harmonized SOC cohort。
- `POST /api/v1/cohort-datasets/{cohort_dataset_id}/lobo-evaluations` 按 `battery_id` 留一电池评估；训练视图不含 held-out 电池标签。`GET /api/v1/cohort-lobo-evaluations/{evaluation_id}` 读取结果。
- V1 只接收满足契约的 Reference SOC 数据集；标签定义和特征定义须兼容，单位必须完全匹配，不执行单位转换。
- 输入 manifest、Parquet 与特征定义 checksum 被追踪。源数据变化后 cohort 会变为 stale，不能作为新评估的有效输入。
- 主要汇总指标为各 held-out 电池等权宏平均；pooled-row 指标仅为诊断项。合成数据测试验证接口和泄漏边界，不构成真实跨电池泛化证据。
- 当前真实 CELL_001 / EXP_001 是单电池样例。跨电池 readiness 必须在至少 2 个独立电池进入兼容 cohort 并通过来源校验后才可能开放。

## 科学边界

- 跨电池泛化使用 `battery_id` 作为外层分组；禁止用随机帧、行、MeasurementEvent 或 SOC 分箱切分代替。
- SOH 的独立样本单位是 cycle/battery 级状态，不能把帧行计作独立健康状态。现有标签构建/离线复用校验不等于 SOH 建模就绪。
- 温度只能来自实测通道；当前规则要求有效温度读数和至少 2 °C 观测范围。不得从超声或其他特征推算温度标签。
- 调参若实现，特征选择与搜索须局限于训练数据中的独立分组验证角色；外层 held-out 标签不得参与选择。
- 不能超过 Dummy 是诚实的科学结果，不是软件故障。增加更复杂的固定模型不构成调参，也不能弥补独立电池或验证数据缺失。
- `READY` 只表示对应 readiness 条件通过，不自动等于生产级证据或普适科学结论。

可执行 contract 定义位于 `src/battery_workbench/api/future_contracts.py`；cohort 请求 schema 位于 `src/battery_workbench/datasets/cohort_schemas.py`。变更 API 状态时应同步此表、API 文档、测试与真实数据证据。
