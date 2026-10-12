# Manifest Data Contract — V1.2

Manifest 是文件系统与数据库之间的显式契约，避免依赖文件名猜测关系。

## batteries.csv

```text
battery_id,chemistry,nominal_capacity_ah,notes
```

## experiments.csv

```text
experiment_id,battery_id,start_time,end_time,protocol,notes,condition_id,condition_description
```

一个 Battery 可以有多个 Experiment。
`condition_id` 与 `condition_description` 是操作者登记的 Experiment 级工况标签/描述；可留空，不能据此推断工况实际执行或经过设备验证。`protocol` 用于记录协议标识/版本。`start_time` / `end_time` 是实验范围描述，不替代逐 DataAsset 的时间戳或声电绝对时间锚点。V1.1 及更早 manifests 若无条件列仍可读取，写入时会保留旧列并补充新列。

当前 `condition_id` 表达一个 Experiment 级归组标签。如果工况在同一 Experiment 内变化，不能把一个单值标签当作时间变化轨迹；需按真实采集边界拆分 Experiment，或在研究侧保留带绝对时间/来源证据的分段清单。Workbench 不会从 Cycle 或文件名推断分段。

## data_assets.csv

```text
asset_id,battery_id,experiment_id,modality,relative_path,file_start_time,file_end_time,parser_name,parser_version,time_anchor_metadata_path
```

一个 Experiment 可以有多个 Electrical DataAsset 和多个 Ultrasound DataAsset。

`battery_id + experiment_id` 是 DataAsset 的复合实验身份。旧版缺少
`battery_id` 的 manifest 仅在 canonical relative path 能明确证明所属 Battery
时向后兼容；不得只凭 `experiment_id` 或文件名匹配。

`file_start_time` 对超声文件非常关键：
每帧绝对时间 = `file_start_time + elapsed_time_s`。

对于有独立采集配置的声学文件，可选填 `time_anchor_metadata_path`，其值是相对
`data/raw/` 的显式路径，例如 `batteries/CELL_001/EXP_001/ultrasound/M2kConfig.xml`。
当前只读取该配置中一致的 `dateAcquis` 字段作为 **PROVISIONAL** 时间锚点候选，
并将相对路径和源文件 SHA256 保存在锚点 evidence 中。该字段必须由操作者确认
配置文件确实对应当前 Ultrasound DataAsset；系统不按目录或文件名自动配对。

M2K `dateAcquis` 不含已确认时区，因此 timezone 仍为 UNKNOWN，时间锚点不会单独
把同步升级为 validated。若 `file_start_time` 与 M2K 时间不同，两者会作为冲突
证据共同保留。存在冲突时标记为 `CONFLICTING`，时间戳构造和后续声电最近邻匹配
都会阻断；解决冲突需补充可审计证据或人工确认，不能仅因某来源优先级较高而继续。
缺少可靠来源时应留空，不能用文件名时间代替。

Cycle 不是 DataAsset 的主键，也不依赖文件名提供。

### Parser 输出完整性

Electrical / Ultrasound `parser_manifest.json` 应记录每个规范解析输出的相对文件名与 SHA-256：Electrical 至少包括 `records`、`cycles`、`steps`，并对实际生成的 `aux_temperature` / `aux_voltage` 一并校验；Ultrasound 必须包括 `frames` 与 `waveforms`。Parquet 按文件字节计算，`waveforms.zarr` 按稳定相对路径与文件字节计算目录树 hash。`output_files` 保存规范 basename，`output_checksums` 保存对应输出键的生成时 checksum；parser manifest 本身不纳入自己的 checksum，避免自引用。

读取端在展示派生统计、运行科学分析或复用 parser 工件前核对 Battery / Experiment 身份、规范输出路径和当前 checksum。输出缺失、路径越界、身份冲突、校验和不匹配或格式非法均属于 integrity failure。缺少输出校验和的旧 manifest 属于 `LEGACY_UNVERIFIED`；不得从当前文件补算历史 hash 后标记为完整。通过 Runs 正常执行对应 Parser Run 重建后，再重新核验同步、MeasurementEvent、label、feature、dataset、model 和 report 等下游派生产物。重解析只恢复“当前解析输出与生成记录一致”的字节完整性，不会自动验证采样率、绝对时间基准、声电同步、标签真实性或特征科学有效性。

### Dataset 对 LabelSet provenance 的固定

Dataset manifest 除记录 `label_set_id`、`label_set_path` 与 event-label Parquet checksum 外，还必须记录 `label_set_manifest_path` 和生成时的 `label_set_manifest_checksum`。读取/复用 Dataset 时应验证该路径为 Experiment canonical `labels/{battery_id}/{experiment_id}/label_manifest.json`、manifest 的 Battery / Experiment / `label_set_id` 与 Dataset 声明一致，并核对 manifest 中 `output_paths.event_labels` 与 `output_checksums.event_labels` 指向同一来源文件。缺少历史 manifest checksum、manifest 身份变化或输出声明不一致时 Dataset 为 stale；不得用当前 LabelManifest 反向补填旧 Dataset 的 provenance。

### Reference LabelSet 版本与电学来源身份

当前 Reference LabelSet contract 为 engine / definition `0.3.0`。`label_manifest.json` 必须同时声明 `label_engine_version` 与 `label_definition_version`；版本不匹配的 LabelSet 在 API、Dataset freshness 与 orchestrator 缓存复用中均视为过期，须通过正常 Run 重建，不能只改 manifest 版本字段。

`event_labels.parquet` 保留每条 MeasurementEvent 所选的 `electrical_asset_id`；没有唯一电学匹配的事件该列保持 null。`cycle_labels.parquet` 保留来源 cycles 表的 `electrical_asset_id`。这些字段用于来源追溯，不是声电同步主键，也不构成跨 DataAsset 的 canonical Cycle 映射。当前若多个 Electrical DataAsset 在同一 Battery/Experiment 复用相同 `cycle_index_raw`，或多资产输入缺失 Cycle/Step 来源键，LabelSet 构建/复用必须 fail-closed；不同文件间 Cycle 连续性仍需显式映射，禁止按文件顺序或 raw Cycle 猜测。

### Dataset 对 FeatureSet provenance 的固定

Dataset manifest 除 FeatureSet Parquet 的 ID、路径和 checksum 外，还必须固定其同目录 `feature_set_manifest.json` 的路径与生成时 SHA-256。读取/复用时校验 FeatureSet manifest 的 Battery / Experiment / FeatureSet 身份、`output_paths.features` / `output_checksums.features` 与 Parquet，以及 `feature_definitions.json` 的规范输出路径与 checksum；并重新验证其声明的 `analysis_slice_path` / checksum 和 `waveform_store_path` / checksum（Zarr 目录按稳定相对路径及文件字节计算 tree SHA-256）。历史 Dataset 缺少生成时 FeatureSet manifest checksum、manifest 输出映射不一致或输入 slice/waveform 已变化时均为 stale；不能以当前 FeatureSet manifest 或当前输入状态补造历史来源证据。该完整性门只证明工件字节与声明一致，不证明采样率、绝对时间同步或特征解释有效。

## Condition Segments sidecar (optional, V1.0)

Experiment-level `condition_id` cannot represent conditions that change during
one acquisition. For explicit, evidence-linked time intervals, see the
[Condition Segments V1.0 contract](condition_segments.md). Store the declaration
outside immutable `data/raw/` at
`data/annotations/{battery_id}/{experiment_id}/condition_segments.csv`; the
[blank CSV template](../templates/condition-segments.csv) is provided. A read-only
validator checks declared intervals against one identified DataAsset's timezone-aware
file bounds, prevents overlaps within a condition axis, and verifies an evidence
file checksum under `data/raw/`. The validation result separately marks the
declared asset-window check as passed while absolute timebase and synchronization
remain `NOT_ASSESSED` and MeasurementEvent assignment remains
`NOT_IMPLEMENTED`. It returns only `OPERATOR_DECLARED` values; no scientific
condition verification is performed by this manifest reader.
