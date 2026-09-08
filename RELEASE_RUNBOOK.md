# RELEASE_RUNBOOK — Battery Research Workbench

## 环境要求

- macOS / Linux
- Python 3.13（uv 管理，`.venv/`）
- Node.js ≥ 22（前端构建/测试）
- 无 GPU 依赖；纯 CPU baselines

## 依赖安装

```bash
# Python（uv）
uv sync                         # 或: python -m venv .venv && .venv/bin/pip install -e ".[dev]"

# 前端
cd frontend && npm ci
```

## 数据放置

```text
data/raw/                              # 只读原始数据（immutable）
├── manifests/{experiments,batteries,data_assets}.csv
└── batteries/CELL_001/EXP_001/{electrical,ultrasound}/
data/processed/                        # canonical artifacts（reproduce 可重建）
data/artifacts/runs/                   # orchestrator run manifests
```

真实数据约定：
- electrical XLSX: `batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx`（sha256 8536d395…）
- ultrasound TXT: `batteries/CELL_001/EXP_001/ultrasound/export - 2024.01.06 - 21.03.01.txt`（sha256 8e196837…）
- 放置后 `data/raw/manifests/data_assets.csv` 已含这两行（勿改 raw）

## 数据库迁移

无外部数据库；所有状态为文件 artifact（parquet/json/zarr）。无迁移步骤。

## 后端启动

```bash
.venv/bin/uvicorn battery_workbench.api.serve:app --port 8000
# OpenAPI: http://localhost:8000/openapi.json（snapshot: docs/api/openapi-v1.json）
```

测试专用（环境门控，无 raw 也拒绝启动）：`battery_workbench.api.serve_sandbox:app`。

## 前端启动

```bash
cd frontend && npx vite --port 5173   # dev
npm run build                         # 生产构建 → dist/
```

## 测试

```bash
.venv/bin/python -m pytest tests/ -W ignore          # 后端全套
cd frontend && npx vitest run                        # 前端全套
cd frontend && npx tsc --noEmit && npm run lint
.venv/bin/python -m ruff check src/ tests/ scripts/
```

## Demo

见 `DEMO_RUNBOOK.md`。

## Artifact 输出位置

| 类型 | 路径 |
|---|---|
| canonical artifacts | `data/processed/{electrical,ultrasound,synchronization,multimodal,labels,features,features_physical,gated_features,analysis_slices,analysis,parameters,datasets,splits,models,feature_analysis}/` |
| runs | `data/artifacts/runs/RUN::*` |
| reports（JSON/MD/HTML） | `data/processed/artifacts/CELL_001/EXP_001/reports/REPORT::*` |
| reproducibility manifest | report 目录内 + clean-room `out/reproducibility_manifest.json` |
| assistant sessions | `data/processed/assistant_sessions/` |

## 清理

```bash
rm -rf data/artifacts/runs/RUN::<id>          # 单个 run
rm -rf /tmp/brw028-clean                      # clean-room 输出
git clean -fdX                                # 忽略文件（node_modules 等）
```

**禁止清理** `data/raw/`（immutable）与 `data/processed/` canonical artifacts。
