# 多电池、多工况声电数据采集与纳入 SOP

版本：1.0

状态：执行前模板；研究负责人须按具体研究问题补齐并批准方案。
适用范围：Battery Research Workbench 中的电学 XLSX、超声 TXT，以及可选的温度、SOC、SOH 参考数据。

本 SOP 用于在采集和导入前固定身份、协议、证据与纳入规则。它不替代设备说明书、伦理/安全要求或研究负责人批准，也不自动验证时间同步、标签准确性或样本量是否充分。未知值应明确写 `UNKNOWN`，不得按文件名、相邻记录或常见设备设置推断。

统计分析决策可从[分析方案空白模板](templates/analysis-plan.yaml)开始填写。当前模板版本为 `brw-analysis-plan-template/1.1`；该 YAML 是供研究负责人讨论、审批和归档的 companion document，不是系统配置，不会自动启用推断。`null` / `UNDECIDED` 表示尚未决定，不等于“没有/不适用”；若决定不计算区间或 p 值、无需多重比较调整、未作混杂调整或不调参，须选择对应 `NOT_PLANNED` / `NOT_APPLICABLE` 状态并填写 rationale。空数组只有与 `REVIEWED_NONE` 或明确的 `NOT_PLANNED` 状态组合时，才表示审查后无项目；不得将模板默认内容解释为本研究已经作出的科学选择。

填写后可做只读的声明完整性预检：

```bash
.venv/bin/python -m battery_workbench.analysis.plan_preflight \
  /path/to/completed-analysis-plan.yaml
```

`INCOMPLETE` 会列出仍为空或 `UNDECIDED` 的字段；`DRAFT_COMPLETE_REQUIRES_APPROVAL` 只表示必需声明已填写，仍须负责人审批。`DECLARATION_COMPLETE_REQUIRES_EVIDENCE_REVIEW` 也不代表实验数据、标签、时间基准或方法科学有效。该预检固定返回 `confirmatory_inference_enabled=false`，不会执行分析、改变 API 的推断状态或解锁数据集/模型流程。

## 1. 采集前冻结研究方案

采集首个样本前，建立有版本和日期的研究方案，并至少记录：

| 字段 | 需记录内容 |
|---|---|
| `study_id` / 版本 | 稳定研究标识、方案版本、生效日期、批准人 |
| 研究问题 | 明确研究对象、条件范围和目标用途；区分探索性与确认性分析 |
| 主要终点 | 标签名称、操作性定义、单位、测量/计算方法、时间粒度、独立实验单位和预期不确定度 |
| 纳入/排除规则 | 以可观测证据表达；预先规定文件缺失、设备故障、传感器失效、协议偏差等处理，不根据模型结果事后改规则 |
| 分析计划 | 候选特征、主要比较、分组变量、重复测量处理、多重比较/不确定性方法；外层评估按 Battery 分组 |
| 样本量依据 | 由研究设计、预期效应/变异、功效或精度目标论证；不得把软件 LOBO 最低 2 块电池门当作科研样本量建议 |
| 时间容差 | 对每种同步/时间锚点比较预先声明允许误差及其依据；没有依据时保持未声明/未验证 |
| 方案变更 | 记录变更日期、理由、影响样本和分析的方式；保留旧版本，不覆盖历史决策 |

确认性研究应在查看外层 held-out 结果前冻结方案、纳入规则、特征/标签定义和评估方法。探索性发现需标记为探索性，后续确认须使用独立数据或预先定义的验证策略。

## 2. 身份和采集设计

1. 为每块实体电池分配唯一、稳定的 `battery_id`；记录化学体系、标称容量及其来源。不得用文件名、Cycle 编号或测量结果代替电池身份。
2. 每次独立采集/实验分配唯一 `experiment_id`，并关联 `battery_id`。记录工况、协议版本、开始/结束时间及时间来源；时间是否带时区必须明确。
3. 每一个原始文件独立登记为 DataAsset；一个 Experiment 可以有多个同模态或异模态文件。不得假设一个文件对应一个 Cycle，也不得用 Cycle 作为跨文件主键。
4. 采集计划应覆盖目标工况，并记录重复实验、静置、充放电阶段、异常中止和未完成采集。计划中的工况与实际执行工况分开记录。
5. 若需要估计跨电池泛化，需确保电池是独立外层单位；同一电池的多个循环、文件、帧或事件不能计作多个独立电池。

Intake 新建实验支持记录 `protocol`、`condition_id`、`condition_description`、`start_time` 和 `end_time`。这些字段按操作者输入写入 Experiment manifest 与 intake import manifest，并标为 `OPERATOR_DECLARED`；系统不验证协议执行、工况真值、设备时钟或时间来源。`start_time` / `end_time` 不作为声电对齐锚点。Workbench 当前只将 `condition_id` 作为 Experiment 级归组标签；同一 Experiment 内工况变化时必须在研究侧定义有证据的分段，不得用一个静态 condition 标签代表整段变化。

同一 Experiment 内需要记录时间变化工况时，可使用[显式 Condition Segments 契约](data_contract/condition_segments.md)与空白[CSV 模板](templates/condition-segments.csv)，将声明作为 sidecar 保存至 `data/annotations/{battery_id}/{experiment_id}/condition_segments.csv`，不要写入 `data/raw/`。每段必须引用同一 Battery/Experiment 下的 time-reference DataAsset、时区明确且落在该资产申报时间范围内，并引用具有匹配 SHA-256 的 `data/raw/` 证据文件。当前 reader 只校验并返回 `OPERATOR_DECLARED` 分段，不把声明升级为验证状态；API 会按同一 DataAsset 时间戳作受限归属，但不会升级时基/同步状态。未经研究负责人定义边界、时间基准与冲突规则，不得将其用于确认性条件推断。

## 3. 每次 Experiment 的采集记录

每次实验至少记录以下内容；不适用项写 `NOT_APPLICABLE`，未知项写 `UNKNOWN`，并尽可能说明未知原因。

- **电池/样品**：`battery_id`、化学体系、标称容量、样品来源、使用历史、预处理状态。敏感信息按机构规则去标识化。
- **工况与电学协议**：充放电/静置步骤、倍率或电流设定、截止电压、循环定义、温箱设定、环境温度、设备型号/序列号、通道、固件/导出软件版本。
- **超声配置**：仪器与换能器型号、探头标识、耦合剂、探头位置/方向/接触方式、夹持压力（若有测量）、传播路径/几何尺寸及其测量来源、触发/采集模式。
- **采样时钟**：波形 `sampling_rate_hz` 的来源（设备配置、原始导出、校准记录或经批准的其他证据）、单位、证据文件及 SHA256、验证状态。帧间采集间隔不是波形采样率。
- **温度**：每个温度通道的传感器 ID、位置、测量对象、单位、校准证书/有效期/量程、通道映射。多个温度通道不得合并成一个未说明的温度目标。
- **SOC/SOH 参考**：SOC 的独立参考测量或派生公式、初始条件、误差/不确定度；SOH 的容量/健康测试协议、测试条件、参考容量和 cycle/battery 粒度。派生 Reference SOC 不得标称为真实 SOC。
- **时间基准**：每台设备的本地时钟/时区、时钟来源、采集开始/结束时间、设备间同步方式、同步脉冲或共同事件、采集日志及其误差。分别记录“波形采样时钟”和“设备绝对时间/声电时钟同步”，不可互相替代。
- **操作偏差**：实际执行与计划不同之处、故障/重启/断连、文件分段、操作人员声明及发生时间；保留失败记录，不只保存成功数据。

### 标签来源与不确定度工作表

可从[目标标签 provenance 工作表](templates/target-label-provenance.yaml)收集 `target-dataset/1.0` 所需字段。它是研究侧 companion worksheet，不是可直接导入的 manifest、API request 或标签工件；模板中的 `null` / 空数组表示尚未提供证据，不是默认科学结论。研究方案、测量定义或来源不足时应保持空缺，不得从文件名、常用设备设置或当前模型结果推断。

完成工作表后，可在仓库根目录运行只读结构预检：

```bash
.venv/bin/python -m battery_workbench.provenance.target_label_worksheet \
  /path/to/completed-target-label-provenance.yaml
```

该命令只校验 YAML 结构及 `target-dataset/1.0` 请求契约，并输出工作表 checksum；空白模板会因科学字段尚未填写而校验失败。通过结果**不**表示来源文件 checksum 已核对、标签语义已验证、target 已 ready 或允许物化数据集。来源文件应另行通过 `POST /api/v1/target-datasets/validate-source-evidence` 预检；该 API 同样不评估科学有效性或开放物化。

当前 contract 固定了目标语义、粒度和单位的组合：`reference_soc_percent` 为 `DERIVED_REFERENCE_LABEL` / `MEASUREMENT_EVENT` / `percent`；`temperature_c` 为 `DIRECT_MEASUREMENT` / `MEASUREMENT_EVENT` / `celsius`；`soh_capacity_reference_percent` 为 `DERIVED_HEALTH_STATE` / `CYCLE` / `percent`。这些是接口一致性门，不证明目标测量有效或达到科研 readiness。SOH 的 `minimum_independent_states` 至少为 3 只是当前软件门，不是研究样本量建议；SOC 与温度不得填写该字段。

来源引用须逐项解析到登记的 Electrical DataAsset，记录其 DataAsset ID、manifest 中的 raw-relative 文件路径和原始文件 SHA-256。公式、sheet/column/record locator、传感器通道、容量测试协议等解释应写入方法定义或对应证据，不要把整个 XLSX checksum 当成某个测量值的充分证据。`QUANTIFIED` 不确定度须来自明确方法、单位和证据；若未知，选择 `UNKNOWN` 并说明原因，不估算数值。只读 `validate-source-evidence` 预检仅核对 DataAsset/字节 provenance；它不会评估这些测量定义或不确定度，也不会物化标签数据集。

## 4. 原始文件与 manifest

原始文件完成采集后立即只读归档，导入前后不得编辑或覆盖。为每个文件记录 SHA256、字节数、原始文件名、采集设备、导出时间和保存位置；同名文件以 DataAsset ID 与 checksum 区分。

工作台的主身份登记仍按现有契约维护：

- `batteries.csv`：Battery 身份及可证实的基本属性；
- `experiments.csv`：Experiment 与 Battery 关系、时间、协议；
- `data_assets.csv`：每个文件的 asset ID、实验身份、modality、相对路径、可证实的文件时间和解析器信息。

导入向导或当前 manifest contract 尚无专用字段时，不要私自扩展 CSV 列并假设程序会消费它；将额外采集证据放在受控的研究记录中，以稳定路径和 checksum 引用。只有来源可靠时才填写 `file_start_time`；缺少时区或设备时钟证据时，时间基准保持 `PROVISIONAL` / `UNKNOWN`。详细字段以[Manifest 数据契约](data_contract/manifests.md)为准。

推荐的批次资产清单（每个原始文件一行）：

可复制填写的 CSV 空模板见[批次资产清单模板](templates/cohort-intake-inventory.csv)。这是研究批次的 companion inventory，用于补充方案、checksum、设备和证据引用；**不是**当前可直接导入的 `data_assets.csv`，不可把它重命名后直接导入。应用 manifest 字段仍以[Manifest 数据契约](data_contract/manifests.md)为准。

| study_id | battery_id | experiment_id | asset_id | modality | relative_path | sha256 | size_bytes | acquisition_device | native_start_time | timezone_status | evidence_ref | planned_role |
|---|---|---|---|---|---|---|---:|---|---|---|---|---|
|  |  |  |  | electrical / ultrasound / reference |  |  |  |  |  | VERIFIED / UNKNOWN |  | primary / supporting / calibration |

`native_start_time` 是设备记录的值；不得为了让文件“对齐”而改写它。校准/同步证据也应登记为独立文件或可追溯记录，不得把原始数据文件 checksum 冒充校准证据 checksum。

电学与超声的预期配对需另行逐对审查，可从[声电配对审查 CSV 模板](templates/cohort-pair-review.csv)开始；将填写后的 study-level 审查表保存为 `data/annotations/studies/{study_id}/cohort-pair-review.csv`。模板行的 `contract_version` 固定为 `cohort-pair-review/1.0`；每行是一项待审 pair，不假设它与一个 Cycle 一一对应。填写两侧 DataAsset 身份/路径/checksum、独立的电池身份依据、配对依据和时间基准证据；三项 review 状态分别使用 `NOT_REVIEWED`、`ACCEPTED` 或 `REJECTED`，总决策使用 `HOLD`、`INCLUDE` 或 `EXCLUDE`。`ACCEPTED` 是签署人的审查声明，不是系统认证或自动同步验证；缺证据时保持 `NOT_REVIEWED` / `HOLD`，不得以目录相邻、文件名相似或时间接近替代身份/配对证据。任何变更都新增审查行并通过 `supersedes_review_id` 指向旧记录，不覆盖旧决策。该模板是 companion audit，不是应用当前可直接导入的 manifest，也不会自动开放 cohort 或升级 `validated_sync`。

对于尚未登记为 Workbench DataAsset 的外部数据，可先对实验方提供的显式 source-map 做只读文件完整性预检：

```bash
.venv/bin/python -m battery_workbench.provenance.source_map_preflight \
  /path/to/source-map.csv --source-root /path/to/raw-data
```

此步骤只核对映射 CSV 的路径、扩展名、文件存在性和 SHA-256，可在正式 Battery/Experiment/DataAsset ID 分配前运行。它不生成/推测这些 ID，也不判断 pair 是否真实、是否同一物理电池/采集，更不验证 absolute timebase。负责人审查后，应按批准的身份把文件正式登记；再运行后文 `cohort_pair_review` 预检核对审计记录与 manifest。不得把 source-map integrity 结果直接转成 cohort `INCLUDE`。

完成每个 pair 的资产身份、来源路径与 checksum、三类审核状态、总决策、审核人/角色、带时区的审核时间和理由后，再对清单做只读完整性预检。**刚复制的空白模板不能直接通过预检**；尚未取得身份/配对/时钟证据时，可以由实际审核人记录 `NOT_REVIEWED` 并将总决策设为 `HOLD`，不得为了通过预检而虚填 `ACCEPTED` 或 `INCLUDE`：

```bash
mkdir -p data/annotations/studies/STUDY_001
cp docs/templates/cohort-pair-review.csv \
  data/annotations/studies/STUDY_001/cohort-pair-review.csv
.venv/bin/python -m battery_workbench.provenance.cohort_pair_review \
  data/annotations/studies/STUDY_001/cohort-pair-review.csv --raw-root data/raw
```

预检会检查注册 DataAsset 的身份/模态/路径、raw-relative 文件 checksum、审核字段格式和修订链；`INCLUDE` 需三项 review 均为 `ACCEPTED` 且各自有匹配的证据路径/hash。输出的 `STRUCTURALLY_VALID` 只表示这份审计 CSV 与当前文件字节结构一致，响应会固定保留 `cohort_admission_authorized=false`、`scientific_identity_status=NOT_ASSESSED` 和 `timebase_validation_status=NOT_ASSESSED`。它不认证 reviewer、身份/配对真值或设备时钟，也不创建/开放 cohort。

## 5. 导入前后质量门

### 导入前

- [ ] 研究方案版本、主要终点、纳入/排除规则和时间误差容差已批准或明确标记待批准。
- [ ] Battery / Experiment / DataAsset 身份唯一且关系可追溯；同一实验的全部文件已逐个登记。
- [ ] 原始文件可读取；文件大小与 SHA256 已记录；原件被只读保存。
- [ ] 电学、超声、温度、标签和时钟的来源分别有证据引用；缺失/未知未用估计值填充。
- [ ] 采集偏差、失败文件、缺失通道与设备告警均有记录。

### 解析与关联后

- [ ] 记录解析器版本、输入 checksum、输出工件身份；解析失败时不得静默跳过资产或行。
- [ ] 检查行数/frame 数、时间范围、重复/倒退时间戳、空值、异常范围和各资产覆盖；保留原始顺序与来源定位。
- [ ] 分别查看每个 Electrical / Ultrasound DataAsset；跨文件关系依据 Battery/Experiment → DataAsset → absolute timestamp → nearest electrical record → Cycle/Step mapping 建立。
- [ ] 检查 `sync_error_s`、歧义、未匹配和边界事件；不得只报告匹配率而隐藏误差或冲突。
- [ ] 抽样追溯原始文件 → 原始行/frame → MeasurementEvent → 特征/标签/报告，并记录抽样规则和结果。
- [ ] 纳入/排除按冻结规则执行；每个排除样本记录对象、理由、规则条款和操作者。原始数据不删除，processed 数据不通过人工改写来“修复”。
- [ ] 对温度、SOC、SOH 等目标逐项核对语义、单位、来源、粒度、测量误差、独立实验单位和覆盖率；未通过证据门的 target 保持 blocked。
- [ ] 模型数据集按 Battery 分组；held-out 标签不参与特征选择、分析决策或调参。

质量门结果建议标为 `PASS`、`FAIL`、`NOT_ASSESSED` 或 `BLOCKED_BY_DATA`。`PASS` 仅适用于该条检查，不自动表示整个实验或科学问题已验证。

若一个 Electrical Experiment 有多个温度通道，生成 MeasurementEvent 时须显式选择。用户可在 Analysis → Alignment 的“Electrical 温度通道来源”面板选择并启动重建；等价的 `/runs` AnalysisPlan 字段为 `"measurement_events": {"temperature_channel_id": "T2"}`。没有选择或所选通道不存在时，物化应阻断；manifest 分开记录请求值 `temperature_channel_id` 和实际采用的 `resolved_temperature_channel_id`，且不同通道选择不能复用彼此工件。单通道时系统可解析唯一通道，并将解析值写入 `resolved_temperature_channel_id`。该选择仅确定事件表中的温度来源，不证明传感器位置/校准有效，不会解除 Temperature target 的验证门。仍须人工确认测量对象和来源证据。

## 6. 批次纳入/排除审计表

每个 Battery/Experiment 和每个被排除的 DataAsset/记录都应能定位到审计条目。可复制以下表格维护批次决策：

| study_id | battery_id | experiment_id | asset_id / scope | rule_id | decision | evidence_ref | reason | reviewer | date |
|---|---|---|---|---|---|---|---|---|---|
|  |  |  |  |  | INCLUDE / EXCLUDE / HOLD |  |  |  |  |

`HOLD` 表示信息待核实，不等于纳入。若决策变化，新增一条记录并引用被替代的决策，不覆盖历史审计。

## 7. 交付给分析人员的批次包

开始特征分析前，批次应至少交付：

1. 已冻结的研究方案及版本历史；
2. Battery / Experiment / DataAsset manifests；
3. 原始文件 checksum 清单及只读归档位置；
4. 设备、工况、环境、传感器位置/校准、采样率和时间同步证据；
5. 标签定义、来源、粒度和不确定度记录；
6. 解析/QA、纳入排除、时间关联与人工抽样追溯结果；
7. 明确列出的未知项、偏差和未通过的质量门。

资料不足时可以继续做格式检查或探索性分析，但报告须保留相应限制；不得将软件流程成功或小样本模型分数解释为生物/电化学机制、状态真值或跨电池泛化证据。
# 研究分析方案登记

研究方案可登记在 `data/annotations/studies/{study_id}/analysis-plan.yaml`。方案中的
`eligible_batteries_and_experiments` 必须显式列出 Battery / Experiment；工作台只按该复合
身份匹配，不依据文件名或目录猜测归属。多份匹配方案、无效文件或不完整方案会作为状态呈现，
不会自动择一，也不会因此开放确认性推断。方案登记状态不代表数据就绪或科学有效性通过。
