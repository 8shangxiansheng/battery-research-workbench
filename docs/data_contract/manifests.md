# Manifest Data Contract — V1.1

Manifest 是文件系统与数据库之间的显式契约，避免依赖文件名猜测关系。

## batteries.csv

```text
battery_id,chemistry,nominal_capacity_ah,notes
```

## experiments.csv

```text
experiment_id,battery_id,start_time,end_time,protocol,notes
```

一个 Battery 可以有多个 Experiment。

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
