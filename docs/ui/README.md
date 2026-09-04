# BRW-025 Scientific Workbench UI — 使用说明

## 启动

### 1. 启动 API（必须先启动）

```bash
# 在仓库根目录
.venv/bin/uvicorn battery_workbench.api.serve:app --port 8000
```

健康检查: `curl http://127.0.0.1:8000/api/v1/health`

### 2. 启动 UI

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 Vite 输出的地址（默认 http://localhost:5173）。
Vite dev server 将 `/api/v1` 代理到 `http://127.0.0.1:8000`（见 `frontend/vite.config.ts`）。

### 3. 生产构建

```bash
cd frontend
npm run build     # tsc + vite build → dist/
npm run preview
```

## API Base

- 开发: UI 通过 Vite proxy 访问 `/api/v1`（同源，无 CORS 问题）。
- typed client: `frontend/src/api/client.ts`，契约对齐 `docs/api/openapi-v1.json`。

## 命令

| 命令 | 位置 | 作用 |
|---|---|---|
| `npm run lint` | frontend/ | ESLint（0 warnings 上限） |
| `npm run typecheck` | frontend/ | tsc 严格模式 |
| `npm test` | frontend/ | Vitest 全量（含 OpenAPI drift 检查） |
| `npm run build` | frontend/ | 生产构建 |
| `.venv/bin/pytest tests/` | 仓库根 | 后端全量回归 |

## 真实 artifact demo

后端 API 使用仓库默认 `data/raw` + `data/processed`（CELL_001/EXP_001 真实产物）。
UI 打开即显示真实 workspace-summary / waveform / features / modeling / evidence。
