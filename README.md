# Battery Research Workbench — V1.1

面向 **锂电池电学 XLSX + 超声 TXT 原始波形** 的可复现、Agent-assisted 科研工作台。

V1.1 已将核心数据模型升级为：

```text
Battery
→ Experiment
→ DataAsset(s)
→ Electrical Record / Ultrasound Frame
→ time synchronization
→ MeasurementEvent
→ Cycle / Step / SOC / SOH
```

因此原生支持：

- 多块 Battery
- 每块 Battery 多次 Experiment
- 每次 Experiment 多个 XLSX/TXT 文件
- 一个文件跨多个 Cycle
- 多个 TXT 覆盖一个 Experiment
- 后续自动 Cycle/Step 映射

## 当前这两个样例文件怎么放

```text
data/raw/batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx
data/raw/batteries/CELL_001/EXP_001/ultrasound/export - 2024.01.06 - 21.03.01.txt
```

然后编辑：

```text
data/raw/manifests/batteries.csv
data/raw/manifests/experiments.csv
data/raw/manifests/data_assets.csv
```

仓库已经放入当前样例对应的 manifest 模板。

## 为什么不按 Cycle 建文件夹？

因为 Cycle 是实验数据里的状态标签，不是可靠的文件身份：

- 一个 XLSX 可以包含多个 Cycle；
- 一个 TXT 可以覆盖多个 Cycle；
- 多个 TXT 也可能属于同一个 Experiment。

正确流程是：

```text
Battery + Experiment
      ↓
DataAsset
      ↓
absolute timestamp
      ↓
nearest electrical record
      ↓
MeasurementEvent
      ↓
Cycle / Step / SOC / T / ...
```

## 目录

```text
data/raw/batteries/               # immutable original files
data/raw/manifests/               # Battery/Experiment/DataAsset mapping
data/processed/electrical/        # Parquet
data/processed/ultrasound/        # Zarr
data/processed/measurement_events/# synchronized multimodal table

src/battery_workbench/domain/     # core entities
src/battery_workbench/registry/   # Battery/Experiment/Asset lookup
src/battery_workbench/io/         # file-format adapters
src/battery_workbench/synchronization/
src/battery_workbench/electrical/
src/battery_workbench/ultrasound/
src/battery_workbench/analysis/
src/battery_workbench/ml/
src/battery_workbench/agent/
```

## 当前开发顺序

1. BRW-003 Electrical Parser
2. BRW-004 Electrical QA
3. BRW-005 Ultrasound Parser
4. BRW-006 Golden validation
5. BRW-008–011 Synchronization + MeasurementEvent
6. Feature/analysis
7. ML
8. Agent
9. UI

不要在同步数据地基完成前优先开发 Agent/UI。

## Electrical QA

BRW-004 对 BRW-003 的标准化 Parquet 输出执行只读质量检查，并生成 canonical JSON、HTML、CSV 汇总与 8 张诊断图：

```python
from pathlib import Path

from battery_workbench.electrical.qa import ElectricalQAConfig, run_electrical_qa

config = ElectricalQAConfig.from_yaml("configs/electrical_qa.yaml")
report = run_electrical_qa(
    "CELL_001",
    "EXP_001",
    Path("data/processed/electrical/CELL_001/EXP_001"),
    Path("data/artifacts/CELL_001/EXP_001/electrical_qa"),
    config,
)
print(report.status)
```

QA 不会删除重复 timestamp、修改异常值或回写 processed Parquet。

## Ultrasound TXT Parser

BRW-005 根据 DataAsset manifest 将一个 Experiment 下的一个或多个 Ultrasound TXT 转为 frame metadata 与独立的 raw waveform Zarr group：

```python
from pathlib import Path

from battery_workbench.io.experiment.manifest_loader import load_data_assets, load_experiments
from battery_workbench.io.ultrasound import parse_ultrasound_experiment, write_ultrasound_experiment

raw_root = Path("data/raw")
assets = [
    asset
    for asset in load_data_assets(raw_root / "manifests/data_assets.csv")
    if asset.modality == "ultrasound" and asset.experiment_id == "EXP_001"
]
experiment = next(
    item
    for item in load_experiments(raw_root / "manifests/experiments.csv")
    if item.experiment_id == "EXP_001"
)
parsed = parse_ultrasound_experiment(experiment, assets, raw_root)
write_ultrasound_experiment(parsed, Path("data/processed/ultrasound"))
```

Parser 保留 raw frame ID、unknown metadata 与整数 waveform，不执行滤波、FFT、TOF 或 Electrical 同步。当前没有可靠 sampling rate，输出中保持 `null`。

## Ultrasound QA

BRW-006 对 BRW-005 的 canonical `frames.parquet`、`waveforms.zarr` 和
`parser_manifest.json` 执行只读质量检查：

```python
from pathlib import Path

from battery_workbench.ultrasound.qa import UltrasoundQAConfig, run_ultrasound_qa

config = UltrasoundQAConfig.from_yaml("configs/ultrasound_qa.yaml")
report = run_ultrasound_qa(
    "CELL_001",
    "EXP_001",
    Path("data/processed/ultrasound/CELL_001/EXP_001"),
    Path("data/artifacts/CELL_001/EXP_001/ultrasound_qa"),
    config,
)
print(report.status)
```

QA 会生成 JSON、HTML、3 张 CSV 表和 8 张诊断图，不会修改 processed 输入或波形。
当前 `sampling_rate_hz=null`，因此图表横轴保持 sample index，且不报告绝对 TOF
或物理频率。

## Run tests

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Key documents

- `docs/development-plan.md`
- `docs/tech-stack.md`
- `docs/data_contract/electrical_xlsx.md`
- `docs/data_contract/ultrasound_txt.md`
- `docs/data_contract/manifests.md`
- `docs/architecture/multi-experiment-synchronization.md`
- `AGENTS.md`
