# Current Ultrasound Baseline

当前真实 TXT 已确认：

```text
frames = 3999
frame_index_raw = 0..3998

semicolon sections/frame = 6

waveform samples/frame = 1250

unknown tail values/frame = 16

first elapsed_time_s = 0.031217
last elapsed_time_s = 39980.03

median frame interval_s = 10.0
```

结构：

```text
field_0 ;
field_1 ;
elapsed_time ;
field_3a field_3b ;
waveform[1250] ;
tail[16]
```

安全 canonical：

```text
frame_index_raw
unknown_field_1
elapsed_time_s
unknown_meta_0
unknown_meta_1
waveform
unknown_tail
```

未知：

```text
waveform sampling frequency
transducer center frequency
gain
trigger semantics
unknown metadata semantics
```

因此当前：

```text
sampling_rate_hz = null
```

且：

```text
TOF in μs = unavailable
frequency in Hz/MHz = unavailable
```
