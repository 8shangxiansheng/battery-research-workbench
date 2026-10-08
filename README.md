# Battery Research Workbench — V1.1

面向 **锂电池电学 XLSX + 超声 TXT 原始波形** 的可复现、Agent-assisted 科研工作台。

## 当前使用状态

工作台已有实验导入、Overview、Waveform、Analysis、Models 和 Report 等用户流程。第一次使用请先阅读[使用指南](docs/USER_GUIDE.md)；它说明 Docker / Windows 部署、实验导入、分析步骤及当前科学限制。本文其余内容主要记录数据架构、开发和部署细节。

当前 CELL_001 / EXP_001 是单电池、两循环样例；时间基准仍需在界面核实是否为 provisional，Reference SOC 是回顾性参考标签，温度通道缺失，SOH 独立状态数量有限。模型与报告是否可运行取决于当前数据集和 grouped split 状态；不要把样例结果表述为跨电池泛化或超参数调优结论。

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

## 初始开发顺序（历史路线图）

以下顺序记录项目最初的数据地基建设计划，不代表当前尚未实现的模块清单。当前用户操作方式见[使用指南](docs/USER_GUIDE.md)，历史任务的交付记录见 `docs/reviews/` 与 `docs/release/`。

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

## Docker deployment (single port: UI + /api/v1)

```bash
docker compose up --build -d
# 打开 http://127.0.0.1:8000/ （前端构建已烤入镜像，同源调 /api/v1）
```

容器 Python runtime 依赖由根目录 `uv.lock` 固定，Docker build 使用 `uv sync --frozen`，并安装 `ml` extra 以启用 Models 功能；修改 `pyproject.toml` 的依赖后，先运行 `uv lock` 并将锁文件一并提交。锁文件覆盖 uv 解析的 Python/platform markers，CI 配置会检查 `linux/amd64` 与 `linux/arm64` 镜像构建。

Compose 默认只监听本机回环地址；需配置 `BRW_PORT` 可改主机端口。由于 API 当前没有认证，**不要直接将 `BRW_BIND_ADDR` 设为 `0.0.0.0` 暴露到不可信网络**；远程使用请置于具备认证与 TLS 的反向代理之后。

Compose 将 `data/raw`、`data/annotations`、`data/processed` 和 `data/artifacts` 分目录挂载。受审 Cycle/Step 映射 sidecar 写入 `data/annotations`，容器重建后仍保留且默认不纳入 Git；部署迁移时应备份该目录。raw 默认可写是为了支持 UI 新建实验/导入原始资产；导入流程只新增源文件和 manifest，不应覆盖已有原始文件。对于只需分析既有数据的部署，可设置 `BRW_RAW_READ_ONLY=true`，但此时 UI 导入功能不可用。Linux 用户需确保挂载目录可由容器 UID/GID（默认 `10001:10001`）写入；例如：

```bash
mkdir -p data/raw data/annotations data/processed data/artifacts
sudo chown -R "${BRW_UID:-10001}:${BRW_GID:-10001}" data/raw data/annotations data/processed data/artifacts
```

也可设置 `BRW_UID` / `BRW_GID` 为当前用户的 UID/GID。Docker Desktop (Windows/macOS) 使用其共享目录权限映射。

需要多架构镜像时，可运行 `docker buildx build --platform linux/amd64,linux/arm64 -t <registry>/brw-workbench:<ver> --push .`。仓库 CI 会对两个平台执行构建检查；这验证 Linux 容器镜像，不代表原生 Windows 容器。

## Key documents

- [User Guide（使用指南）](docs/USER_GUIDE.md)
- `docs/development-plan.md`
- `docs/tech-stack.md`
- `docs/data_contract/electrical_xlsx.md`
- `docs/data_contract/ultrasound_txt.md`
- `docs/data_contract/manifests.md`
- `docs/architecture/multi-experiment-synchronization.md`
- `AGENTS.md`
