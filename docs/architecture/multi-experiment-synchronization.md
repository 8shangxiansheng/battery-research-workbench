# Multi-Battery / Multi-Experiment Synchronization Architecture

## Core identity hierarchy

```text
Battery
  └── Experiment
        ├── Electrical DataAsset(s)
        └── Ultrasound DataAsset(s)
                ↓
          absolute timestamps
                ↓
          nearest-time alignment
                ↓
          MeasurementEvent
                ↓
      Cycle / Step / SOC / SOH
```

## Why Cycle is not a folder/key

A single XLSX can contain many cycles.
A single TXT can span many cycles.
Multiple TXT files can also belong to one experiment.

Therefore:

1. First identify `Battery + Experiment`.
2. Convert each ultrasound frame to an absolute timestamp.
3. Match it to the closest electrical record.
4. Only then inherit Cycle, Step, SOC, temperature and other state variables.
5. Persist `sync_error_s` and boundary/drift quality flags.

## Synchronization levels

### Level 1 — Offset only (V1 default)

```text
t_abs = file_start_time + elapsed_time
```

### Level 2 — Offset + clock drift

```text
t_abs = file_start_time + a + b * elapsed_time
```

Enable only when QA shows systematic drift.

### Level 3 — Piecewise synchronization

Reserved for later datasets that require per-file/per-segment clock correction.
