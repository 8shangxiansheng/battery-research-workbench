# 科学工作流（V2 导航）

实验总览（高层摘要卡 + Pipeline Stepper + next-action 按钮卡）→
数据（Assets/Quality/Sync/Events 分页）→ 波形与闸门（大波形 + zoom/pan + draft/committed gate）→
特征（CORE/DERIVED/AUXILIARY 折叠；TOF blocked = null+reason，绝不 0）→
特征分析（Exploratory/ML-safe 顶部切换；API 未提供的指标显示"当前后端未提供"，不前端重算）→
数据集与划分（grouped TRAIN/HELD_OUT；2 组不支持 3-way，无 random-row fallback）→
SOC 建模（Dummy 基线高亮；弱结果诚实横幅；无 tuning）→
科学报告（幂等 REUSED）→ 证据与血缘（EvidenceType 视觉分级 + lineage 下钻）→
运行（WAITING_FOR_USER 抽屉：原因/字段/影响/submit/resume）。
