# 科学工作流（UI 操作路径）

1. **工作区 Workspace** — 打开 `/experiments/CELL_001/EXP_001/workspace`。
   readiness / limitations / next_actions 全部来自 `GET /workspace-summary`，UI 不自行推导。
2. **波形与闸门** — 选择帧 → 波形预览（API 降采样，x 轴 = Sample Index，因为采样频率未验证）
   → 拖选区间生成 draft gate（橙色）→ 填显示名 → 提交（POST /gates，蓝色 committed）。
3. **特征** — CORE（tof/amplitude）优先；AUXILIARY 折叠；TOF 显示 BLOCKED + 原因（值 null，不显示 0）。
   勾选 = draft FeatureLocator 选择。
4. **特征分析** — 显式选择 EXPLORATORY_FULL_DATA（显示 not-ML-safe 横幅）或 TRAIN_ONLY_ML_SAFE
   （TRAIN 参与 selection；HELD_OUT 不参与）。提交 POST /feature-analyses。
   相关性表渲染 API 数据，UI 不重算；不自动命名 Best Feature。
5. **确认特征选择** — 走运行记录页的 UserActionRequired（API confirmation contract）。
   确认前不自动构建数据集。
6. **数据集与划分** — POST /datasets（同 spec 幂等 REUSED）→ POST /splits。
   LEAVE_ONE_GROUP_OUT：TRAIN/HELD_OUT 分组（group_column=cycle_group_id）。
   2 个独立 cycle 不支持 3-way；无 random row fallback。
7. **SOC 建模** — Dummy/Linear/Ridge/RF/GB 的 per-fold + macro 指标（GET results）。
   无 tuning 控件。真实结果弱于 Dummy 时显示诚实结论横幅。
8. **科学报告** — POST /reports（聚合既有产物，幂等 REUSED，不触发 refit）。
9. **证据与血缘** — 每个数值可追溯到 EvidenceType（直接产物/既往审计等视觉区分）→ limitations → lineage。
10. **运行记录** — REUSED/EXECUTED/BLOCKED/WAITING_FOR_USER。
    WAITING_FOR_USER：显示科学原因 → 用户输入（如采样率 MHz，客户端只做单位换算，不猜数值）
    → POST user-actions → resume → 状态更新（5s 轮询）。
