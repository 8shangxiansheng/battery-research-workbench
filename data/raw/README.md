# Raw Data Layout — V1.1

原始数据按 **Battery → Experiment → Modality** 组织，而不是按 Cycle 建文件夹。

```text
data/raw/
├── batteries/
│   ├── CELL_001/
│   │   ├── EXP_001/
│   │   │   ├── electrical/
│   │   │   │   └── *.xlsx
│   │   │   └── ultrasound/
│   │   │       └── *.txt
│   │   └── EXP_002/
│   └── CELL_002/
└── manifests/
    ├── batteries.csv
    ├── experiments.csv
    └── data_assets.csv
```

## 当前这组样例数据应该放在

```text
data/raw/batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx
data/raw/batteries/CELL_001/EXP_001/ultrasound/export - 2024.01.06 - 21.03.01.txt
```

Cycle / Step 不作为目录层级，因为一个 XLSX/TXT 都可能横跨多个 Cycle。
Cycle 最终由同步后的时间戳从 Electrical Records 自动映射得到。

> `data/raw/` 永远不可被程序覆盖或修改。
