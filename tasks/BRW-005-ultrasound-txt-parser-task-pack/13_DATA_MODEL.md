# BRW-005 Ultrasound Data Model

## Frame identity

推荐唯一定位：

```text
battery_id
+
experiment_id
+
ultrasound_asset_id
+
frame_index_raw
```

## frames.parquet example

```text
battery_id
experiment_id
ultrasound_asset_id
source_file
source_line_index
frame_index_raw
elapsed_time_s
unknown_field_1
unknown_meta_0
unknown_meta_1
unknown_tail
waveform_store_uri
waveform_group
waveform_row_index
waveform_sample_count
file_start_time
absolute_timestamp
```

## Zarr

```text
waveforms.zarr
└── U001
    └── waveform[n_frames, n_samples]
```

## Why metadata and waveform are separated

Metadata：
- filter/query friendly
- small
- Parquet efficient

Waveform：
- dense numeric matrix
- potentially huge
- Zarr chunking/compression efficient

不要把 1250 点展开成 1250 个 Parquet columns。
