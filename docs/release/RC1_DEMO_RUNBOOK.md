# BRW-RC1 Demo Runbook (10 分钟)

前置：`cd` 仓库根目录。
```bash
.venv/bin/uvicorn battery_workbench.api.serve:app --port 8000   # 后端
cd frontend && npm run dev                                       # 前端 http://localhost:5173
```
实验：CELL_001 / EXP_001（canonical demo 链，全部工件 CURRENT）。

| # | 时间 | 动作 | 预期状态 | 兜底 |
|---|---|---|---|---|
| 1 | 0:00–1:00 | 打开 `/experiments/CELL_001/EXP_001/overview` | 状态横幅、readiness 矩阵、推荐下一步；工件新鲜度 CURRENT | 空白→检查 8000 API |
| 2 | 1:00–2:00 | Overview 滚动：电气快照 / 超声 TOF / 模型基线对比 | Dummy 30.72% 领先，"没有模型跑赢 Dummy" 明示 | — |
| 3 | 2:00–3:00 | 「波形与闸门」页 | 冻结 GC-TOF::e401fecb（v20）+ 包络曲线 + surface/bottom 闸门 | — |
| 4 | 3:00–4:00 | 「特征分析」：目标卡 Reference SOC | 显示"回顾性分段归一化参考标签 — 非真实 SOC" | — |
| 5 | 4:00–5:00 | 特征目录：规范包络峰 TOF / 幅值 / SWA / BPS / TD-FD | tof_us 可勾选，units µs，来源=canonical 工件 | — |
| 6 | 5:00–6:00 | X/y 预览（exactly one y） | 3995 行、排除原因 {AMBIGUOUS_SYNC:4,…}、行溯源 | — |
| 7 | 6:00–7:00 | ML-safe Review（绑定 SPLIT::23ebb24f） | HELD_OUT 行 y=null（后端遮蔽，DevTools 可证） | 演示 fold1 |
| 8 | 7:00–8:00 | 「SOC 建模」 | 5 固定模型 vs Dummy；无 tuning；评估范围"有限" | — |
| 9 | 8:00–9:00 | 右下角 Research Assistant：问"下一步应该做什么" | 回答与 stepper 一致（OPEN_REPORT，typed 导航） | 再问"这个模型用了新的TOF吗" |
| 10 | 9:00–10:00 | 「科学报告」 | REPORT::5b6cf84d，数值均带证据引用，不重训练 | — |

走查提示：Back/Forward/Refresh/深链 `/models` 直达均已验证。
禁止话术：production-ready / cross-battery validated / true SOC / 绝对物理真值。
