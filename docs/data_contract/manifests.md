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
asset_id,experiment_id,modality,relative_path,file_start_time,file_end_time,parser_name,parser_version
```

一个 Experiment 可以有多个 Electrical DataAsset 和多个 Ultrasound DataAsset。

`file_start_time` 对超声文件非常关键：
每帧绝对时间 = `file_start_time + elapsed_time_s`。

Cycle 不是 DataAsset 的主键，也不依赖文件名提供。
