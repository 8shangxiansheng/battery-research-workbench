# Scientific Workbench UI V2

## 启动

```bash
# 1. API
.venv/bin/uvicorn battery_workbench.api.serve:app --port 8000
# 2. UI
cd frontend && npm run dev   # http://localhost:5173
```

## 首页 = Experiment Library

首屏列出全部实验（搜索 / 状态过滤 / Demo 过滤 / 分页）。
- `+ 新建实验` → 6 步 Wizard
- `加载 Demo` → 将内置 CELL_001/EXP_001 注册进实验库（is_demo=true，幂等）
- 空态：「创建第一个实验」「加载 Demo」

## 导航（§19）

实验（总览）｜数据（Assets/Quality/Sync/Events）｜超声（波形与闸门/特征）｜
分析（特征分析/数据集与划分）｜评估（SOC 建模）｜结果（报告/证据血缘）｜运行

## 命令

| 命令 | 说明 |
|---|---|
| npm test | Vitest（含 OpenAPI drift + V2 API contracts） |
| npm run lint / typecheck / build | 门禁 |
| .venv/bin/pytest tests/ | 后端全量 |
