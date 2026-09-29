# Scientific Workbench UI V2

> 用户操作请优先阅读[工作台使用指南](../USER_GUIDE.md)。本文件描述 UI V2 的入口与实现分区，不替代当前版本的逐步操作说明。

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

## 当前主导航

Overview（总览）｜Waveform（波形与闸门）｜Analysis（特征、关系、数据集与划分）｜
Models（建模评估）｜Report（科学报告）

Parameters、Evidence、Lineage、Artifacts、Runs 等高级信息通过 Advanced 或页面内的渐进披露入口访问。Research Assistant 是全局侧边 Drawer，不代表已启用额外 Agent 科学推理能力。

科学工作流状态以当前后端 API 为准：目标 / 对齐 / 特征 / 预览 / 数据集 / 分组划分 / 模型 / 报告。条件未满足时显示 BLOCKED 或 WAITING，并通过页面提供的恢复入口继续；不要用旧导航截图或旧 artifact 推断当前状态。

## 命令

| 命令 | 说明 |
|---|---|
| npm test | Vitest（含 OpenAPI drift + V2 API contracts） |
| npm run lint / typecheck / build | 门禁 |
| .venv/bin/pytest tests/ | 后端全量 |
