# BRW-007 — Data Adapter Registry & Experiment Import Orchestrator

把整个 `BRW-007/` 文件夹放到仓库：

```text
battery-research-workbench/
└── tasks/
    └── BRW-007/
```

然后让 Coding Agent：

1. 先读仓库根目录 `AGENTS.md`
2. 再读 `tasks/BRW-007/01_MASTER_PROMPT.md`
3. 第一轮只 Inspect
4. 第二轮 tests-first
5. 再实现 Adapter / Registry / Importer

---

## BRW-007 的唯一目标

把现有：

```text
Electrical Parser
Ultrasound Parser
```

统一收口为：

```text
Experiment
↓
DataAssets
↓
group by modality
↓
Adapter Registry
↓
Modality Adapter
↓
existing parser/service
↓
ExperimentImportResult
```

---

## 本轮不做

- 新 Parser
- 修改 BRW-003 scientific/data semantics
- 修改 BRW-005 scientific/data semantics
- Electrical–Ultrasound synchronization
- Cycle mapping
- Time anchor
- Feature extraction
- ML
- Agent
- UI
- BEEP / cellpy

---

## 当前真实 baseline

```text
CELL_001 / EXP_001

E001 → electrical
U001 → ultrasound
```

BRW-007 dry-run 最低应该识别：

```text
EXP_001
├── electrical
│   ├── adapter: ElectricalAdapter
│   └── assets: [E001]
└── ultrasound
    ├── adapter: UltrasoundAdapter
    └── assets: [U001]
```
