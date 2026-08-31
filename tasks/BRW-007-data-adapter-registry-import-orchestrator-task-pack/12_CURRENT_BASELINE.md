# Current Baseline

```text
CELL_001
└── EXP_001
    ├── E001 electrical
    └── U001 ultrasound
```

Processed outputs already exist:

```text
data/processed/electrical/CELL_001/EXP_001/
data/processed/ultrasound/CELL_001/EXP_001/
```

Therefore BRW-007 real integration should prefer:

```text
plan only
or
overwrite=False + skip-existing
```

Do not overwrite current Golden outputs.
