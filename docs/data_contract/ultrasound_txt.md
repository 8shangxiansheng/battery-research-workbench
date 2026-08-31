# Ultrasound TXT Data Contract — v0.1

Source example: `export - 2024.01.06 - 21.03.01.txt`

## Confirmed physical file structure

Each non-empty line is one ultrasound frame and currently has exactly **6 semicolon-separated sections**:

```text
field_0 ;
field_1 ;
elapsed_time_s ;
field_3a field_3b ;
waveform[1250] ;
tail[16]
```

Current safe canonical names:

```text
frame_index_raw
unknown_field_1
elapsed_time_s
unknown_meta_0
unknown_meta_1
waveform[1250]
unknown_tail[16]
```

Do **not** rename unknown fields until instrument documentation or external evidence confirms their meaning.

## Golden facts for current sample

- frames: **3999**
- frame IDs: **0–3998**
- sections/frame: **[6]**
- waveform samples/frame: **[1250]**
- tail values/frame: **[16]**
- first elapsed time: **0.031217 s**
- last elapsed time: **39980.030 s**
- median frame interval: **10.000000 s**

## Important scientific limitation

The ~10 s interval is the **frame acquisition interval**, not the waveform sampling frequency.

Without waveform sampling frequency `fs`, it is valid to compute:
- amplitude statistics
- RMS / energy
- peak index
- envelope peak index
- relative cross-correlation shift in samples

It is **not** valid to report:
- absolute TOF in µs
- frequency axis in Hz/MHz

until `fs` is known.

## Parser rules

1. Each frame must preserve all six sections.
2. `waveform` length must be validated.
3. Frame IDs and elapsed times must be monotonic.
4. Unknown fields must survive round-trip metadata handling.
5. Invalid lines must raise explicit validation errors; do not silently skip.

## Canonical storage

- `frames.parquet` stores provenance, raw metadata and a Zarr locator; waveform samples are not expanded into metadata columns.
- `waveforms.zarr/{ultrasound_asset_id}/waveform` stores one `int32` frame × sample array per DataAsset.
- Multiple DataAssets may restart `frame_index_raw` at zero; `ultrasound_asset_id` remains part of frame identity.
- When manifest `file_start_time` is available, `absolute_timestamp` is mechanically calculated as `file_start_time + elapsed_time_s`. This is not validated multimodal synchronization.
- `sampling_rate_hz` remains `null` until supported by reliable external evidence.
