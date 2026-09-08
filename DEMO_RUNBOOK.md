# DEMO_RUNBOOK — Battery Research Workbench 科学演示脚本

**演示实验**: CELL_001 / EXP_001（真实数据，Demo 标记）
**时长**: ~10 分钟
**前置**: 服务已启动（见下）

## 启动

```bash
# 后端 :8000（真实 CELL_001/EXP_001 artifacts）
.venv/bin/uvicorn battery_workbench.api.serve:app --port 8000 &

# 前端 :5173
cd frontend && npx vite --port 5173 &

# 验证
curl -s http://localhost:8000/api/v1/health
```

浏览器打开 `http://localhost:5173`，选择实验 **CELL_001 / EXP_001**。

## Click Path（10 分钟故事）

| # | 页面 | 动作 | 预期可见 |
|---|---|---|---|
| 1 | 总览 | — | 实验摘要、评估完成 · 有限范围徽章、Dummy 基准 MAE 29.61 |
| 2 | 波形与闸门 | 浏览帧 1，查看 5 张物理特征卡 + Electrical State | Bottom-wave Amplitude / SWA / XCorr TOF / Attenuation / BPS 实测值；"同一 MeasurementEvent" 电学状态面板；Calibrate Gates 区 |
| 3 | 特征分析 | Target 步骤选 **Reference SOC / 参考 SOC** | 卡片显示 "Retrospective segment-normalized reference label / 回顾性分段归一化参考标签"；禁止出现 True SOC |
| 4 | Alignment | 步骤 2（对齐） | 7 计数卡：3,999 / 3,995 / 4 / 0 / 3,995 / 3,995 / 4；"PROVISIONAL timebase · validated_sync=false" 徽章；sync error 0.0312s；点击行看 provenance（ambiguous 行 electrical=null） |
| 5 | Features | 步骤 3 勾选 SWA / BOTTOM_AMP / TOF_XCORR | 33 条双语目录（TD 19 + FD 14），TDK/TDV 显示"待 MATLAB 对齐" |
| 6 | Feature–Label Table | 步骤 6 点击"预览特征-标签表" | 一行 = 一个 eligible MeasurementEvent；行数漏斗 3999→3999→3995；行 provenance 抽屉 |
| 7 | Relationships | 步骤 4 点"特征排序" | SWA Pearson +0.514（充电）/ −0.693（放电）→ "方向不同 / Direction-dependent" 徽章；"较高相关性不代表因果关系" |
| 8 | Selection | 步骤 5 切换"为建模选择特征" | TRAIN-ONLY ML-SAFE 徽章；探索排序不能直接建模的说明 |
| 9 | Dataset | 步骤 6 Build ML-safe Dataset → 确认 | X/y 预览（Predictors + Target(y)=Reference SOC + provenance）；handoff 指向 grouped split |
| 10 | SOC 建模 | Advanced → Splits 已就绪；打开 SOC 建模页 | Dummy 均值宏观 MAE 29.61；"当前没有任何模型跑赢 Dummy 基准…这是科学结论，不是处理故障" |
| 11 | Research Assistant | 顶栏按钮打开抽屉 | 输入"帮我研究SOC"→ retrospective 说明 + 1-3 个 next actions；输入"训练SOH模型"→ 2 独立状态阻塞卡 |
| 12 | 科学报告 | 报告页 | Selected features 双语表；Feature workbench summary；limitations 列表（PROVISIONAL_TIMEBASE 等） |

## 预期科学限制（必须如实呈现）

- **provisional timebase**（validated_sync=false，非完全验证同步）
- **仅 2 个循环**（TWO_CYCLES_ONLY）
- **单电池**（ONE_BATTERY_ONLY，无跨电池结论）
- **SOH limited**（2 个独立状态，不建模）
- **Temperature 不可用**（CELL_001 无温度通道）
- **TOF 采样域**（无 fs 不报 µs；物理时间需已验证采样率）
- **模型弱**（全部输 Dummy —— 科学结论，非故障）

## Fallback（演示故障应对）

| 症状 | 处置 |
|---|---|
| :8000 无响应 | 重启 uvicorn（命令同上）；刷新页面 |
| :5173 空白 | 检查 vite 终端；硬刷新（⌘⇧R） |
| 截图/SO 阻塞 | 全部科学数据来自 API，重启后端即可恢复 |
| Agent 无响应 | 抽屉显示错误提示；重开会话（POST assistant/session 幂等） |
| 数据缺失 | 确认 `data/processed/multimodal/CELL_001/EXP_001/` 存在 |

## 已知演示边界

- 演示数据为单电池 2 循环，模型指标弱是数据量所致
- 前端不计算任何科学数值（数值全部来自后端确定性模块）
- 报告生成不触发重训练
