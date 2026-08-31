# BRW-005 Test Plan

## T01 Valid synthetic line

Expected：
6 sections，1250 waveform values，16 tail values。

## T02 Wrong section count

Expected：
`UltrasoundFormatError`。

## T03 Wrong waveform length

Test：
1249 / 1251。

Expected：
explicit error。

## T04 Wrong tail length

Expected：
explicit error。

## T05 Invalid waveform token

Example：

```text
12 13 bad 15
```

Expected：
error includes asset/file/line。

## T06 Non-monotonic elapsed time

Expected：
validation warning/error；
do not sort and hide issue。

## T07 Raw frame index gap

Example：

```text
0,1,3
```

Expected：
preserved + diagnostic。

## T08 Multiple TXT assets

Both start raw frame ID 0.

Expected：
distinguished by `ultrasound_asset_id`。

## T09 Zarr round trip

Randomly verify at least：

```text
20 frames × 3 sample positions
```

or equivalent deterministic golden positions.

## T10 Parquet round trip

Expected：
metadata/provenance stable。

## T11 Current real asset

Baseline：

```text
frames=3999
IDs=0..3998
samples=1250
tail=16
elapsed=0.031217..39980.03
median interval≈10s
```

## T12 Golden raw values

Check：

```text
frame 0
frame 1000
frame 2000
frame 3000
frame 3998
```

At least:

```text
waveform[0]
waveform[10]
waveform[-1]
```

## T13 Raw SHA256

Expected unchanged.

## T14 Missing file_start_time

Expected：

```text
absolute_timestamp = null
warning recorded
```

## T15 Known file_start_time

Expected：

```text
absolute = file_start + elapsed
```

No electrical matching.

## T16 Sampling-rate guard

If sampling rate unavailable：

Expected parser manifest：

```text
sampling_rate_hz = null
```

No derived Hz / μs field generated.
