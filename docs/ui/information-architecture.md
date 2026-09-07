# Information Architecture — Scientific Workbench

## 主导航（5 项，科研任务导向）

| 项 | 路由 | 内容 |
|---|---|---|
| **Overview** | `/experiments/:b/:e/overview` | 5 秒内回答：当前实验？数据就绪？能分析什么？最新发现？下一步？ |
| **Waveform** | `…/waveform` | 产品主角：帧导航 + Plotly 波形 + gate overlay + zoom/pan/select |
| **Analysis** | `…/analysis` | Core features 优先（Amplitude/TOF/Wave speed），More features 折叠；探索/ML-safe 两模式 |
| **Models** | `…/models` | "Did any model beat Dummy?" 科学结论先行，表格其次；Advanced 折叠 fold/RMSE/R²/OOB |
| **Report** | `…/report` | 最新报告 + key findings + limitations；evidence/reproducibility 可展开 |

## Secondary / Advanced（不进主导航）

侧边栏底部 **Advanced** 入口 → `…/advanced/:section`：

- `parameters` — Sampling rate / Trigger / System delay / Reference capacity / Acoustic path（provenance 折叠）
- `evidence` — 证据注册表（type/source/availability）
- `lineage` — Raw → Sync → Events → Features/Labels → Dataset → Split → Model → Report
- `artifacts` / `runs` / `data` / `dataset-split` — 旧调试页保留路由但归入 Advanced

## 全局

- **Experiment Switcher**（topbar，searchable Command combobox + Demo badge）
- **Research Assistant Drawer**（右下角按钮 → 右侧 Sheet：当前上下文 + 建议问题；无 Agent 推理）
- **Experiment library**（`/`）与 **New Experiment Wizard**（`/new`）在库级路由

## 原则

- 用户看到科研任务，不是内部 pipeline —— Artifacts/MeasurementEvents/Parameters/Datasets/
  Splits/Evidence/Lineage/Manifests/Runs 不出现在主导航
- 内部 ID（DS:: / PS:: / BRW-xxx）不作为视觉主角；Advanced 详情可见可复制
- 渐进披露：普通用户先看核心，高级用户可展开全部
