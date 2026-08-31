# BRW-013 Handoff

BRW-013 should consume:

```text
analysis_slice.parquet
+
waveforms.zarr
```

for deterministic Ultrasound Feature Extraction.

BRW-013 must not redo filtering, synchronization, or electrical joining.

Safe future sample-domain features without sampling rate may include:

```text
min/max
mean/std
RMS
P2P
energy-like sample-domain metrics
peak sample index
envelope peak sample index
relative cross-correlation shift in samples
```

Still forbidden without reliable sampling rate:

```text
absolute TOF in µs
physical frequency Hz/MHz
```
