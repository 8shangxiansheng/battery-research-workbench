# Current Ultrasound QA Baseline

```text
CELL_001 / EXP_001 / U001
frames = 3999
frame_index_raw = 0..3998
shape = (3999, 1250)
dtype = int32
global min = -29123
global max = 29392
elapsed = 0.031217 .. 39980.03 s
median interval = 10.0 s
sampling_rate_hz = null
```

BRW-005 Golden 已完成：Frame 0/1000/2000/3000/3998 × sample 0/10/1249 = 15/15 exact match。

因此 BRW-006 的重点是质量，不再重新证明 parser 逐值正确。
