# BRW-005 Functional Specification

## Input

Source of truth：

```text
data/raw/manifests/data_assets.csv
```

过滤：

```text
modality == ultrasound
```

每个 DataAsset 指向一个 immutable TXT。

---

## Public API

推荐：

```python
parse_ultrasound_asset(
    asset: DataAsset,
    raw_root: Path,
) -> UltrasoundAssetParseResult

parse_ultrasound_experiment(
    experiment: Experiment,
    assets: list[DataAsset],
    raw_root: Path,
) -> UltrasoundExperimentParseResult

write_ultrasound_experiment(
    result: UltrasoundExperimentParseResult,
    output_root: Path,
) -> UltrasoundOutputManifest
```

---

## Separation of responsibility

`custom_txt.py`

> 一行/一个文件怎么读？

`service.py`

> 哪些 TXT 属于当前 Experiment？如何生成统一 metadata 和 Zarr？

`validation.py`

> 格式是否满足 Data Contract？

`storage/zarr_store.py`

> 波形如何安全写入/读取？

---

## Identity

唯一定位一条波形应至少使用：

```text
battery_id
experiment_id
ultrasound_asset_id
frame_index_raw
```

不要只用：

```text
frame_index_raw
```

因为多个 TXT 都可能从 0 开始。
