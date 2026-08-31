# BRW-005 Output Contract

## Root

```text
data/processed/ultrasound/{battery_id}/{experiment_id}/
```

## Required

```text
frames.parquet
waveforms.zarr/
parser_manifest.json
```

---

## frames.parquet

只存 metadata/provenance 和 Zarr locator。

不要：

```text
waveform_0000
waveform_0001
...
waveform_1249
```

这种 1250 列设计。

---

## Zarr hierarchy

```text
waveforms.zarr/
├── U001/
│   └── waveform
├── U002/
│   └── waveform
└── ...
```

每个 group 对应一个原始 Ultrasound DataAsset。

---

## Round-trip invariant

Zarr：

```text
raw TXT sample
=
parsed frame sample
=
Zarr reloaded sample
```

Golden check 必须做到整数逐值一致。

---

## No scientific transformation

BRW-005 output 必须是 raw-equivalent parsed representation：

```text
no filtering
no smoothing
no normalization
no alignment
no resampling
```
