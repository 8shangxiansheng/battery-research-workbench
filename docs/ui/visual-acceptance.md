# Visual Acceptance — 视觉验收

视口 **1440×900**，截图来自实际运行 frontend（Vite dev + 真实 API），
基线存于 `docs/ui/screenshots/`。禁止用 Figma/mock 代替。

## 截图清单

| 文件 | 页面/状态 | 验收要点 |
|---|---|---|
| 01_overview.png | Overview | 数据就绪三行、analysis readiness、latest finding、主按钮 |
| 02_waveform.png | Waveform | 大波形、帧导航、工具栏、gate overlay |
| 03_waveform_tof_blocked.png | Waveform TOF blocked | TOF "—" + Sampling rate required + [Add sampling rate] |
| 04_analysis_core.png | Analysis core | Core features 卡片 + 两模式 radio |
| 05_analysis_expanded.png | Analysis expanded | More features 折叠展开、候选特征可勾选 |
| 06_models.png | Models | "No evaluated model outperformed Dummy Mean" + Dummy 高亮表 |
| 07_report.png | Report | 最新报告 + findings + limitations |
| 08_advanced_parameters.png | Advanced→Parameters | 5 参数卡 + provenance 折叠 |
| 09_assistant_drawer.png | Assistant Drawer | 右侧 Sheet、当前上下文、建议问题、"not connected" 声明 |
| 10_empty_state.png | Empty state | 无模型评估时的友好引导 [Go to Analysis] |

## 逐图人工检查

- 3 秒内识别页面目的
- primary action 明确
- current experiment 明显（topbar switcher）
- 内部 ID 隐藏（仅 Advanced 可见）
- blocked state 可理解（非 ERROR 红框）
- 视觉噪音低
- 产品语言一致（一个连贯产品）

## 再生成

```bash
cd frontend && node screenshot-suite.mjs   # 需要 API:8000 + UI:5173 运行中
```
