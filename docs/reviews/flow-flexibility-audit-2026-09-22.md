# 分析流程堵点与灵活性审计（2026-09-22）

范围：特征分析 6 步主流程（目标→对齐→特征→关系→筛选→数据集）+ 相邻页面 + Agent。
方式：真实浏览器逐步走查（CELL_001/EXP_001 实数据）+ 代码审查 + 后端实测。
原则：只增加灵活性与说明性；分析逻辑一律保持后端确定性计算，不改任何科学算法。

## A. 硬堵点（已修复）

1. **ML-safe 无法选择 fold** — Step 5 的 split/fold 完全由“已物化分析匹配”隐式
   决定，匹配不到就只剩“请先建分组划分”的误导提示（split 明明存在）。
   修复：新增只读端点 `GET /experiments/{b}/{e}/splits/{split_id}/folds`
   （fold + TRAIN/HELD_OUT 行数），Step 5 出现 fold 选择器
   （`fold1 · TRAIN 1903/HELD 2092 / fold2 · TRAIN 2092/HELD 1903`）；
   无匹配分析也可直接按所选 fold 的 TRAIN 子集算 ranking/preview。
   实测：选 fold2 后 ranking n_valid=2092，与 folds 端点、split_assignments
   三方一致。
2. **非 SOC 目标在 Step 6 可点“构建”** — SOH/Temperature 的 build 按钮此前
   仅受“已选特征”约束，点击会在 `datasets/…/SOC/` 下写出目标错配的
   SPEC_PENDING 伪产物。修复（双层）：
   - 后端 `create_dataset`：显式 spec 且目标非 Reference SOC →
     `SCIENTIFIC_READINESS_BLOCKED` + 中文原因（SOH 仅 2 独立状态 /
     温度无通道 / 仅物化 SOC 族）；最小 resolve 请求路径不变。
   - 前端：按钮直接禁用并显示原因行（`build-blocked-reason`），
     未选特征时也给出提示。
3. **ML-safe 对 SOH/Temperature 的提示误导** — 之前统一说“先建分组划分”，
   真实原因是该目标不支持 ML-safe 筛选。修复：明确提示并按 EXPLORATORY
   展示（badge 如实显示 `EXPLORATORY · 非 ML-safe`）。

## B. 摩擦点（已修复）

4. **刷新丢失步骤位置** — step 现镜像到 `?step=`，深链
   `/analysis?step=selection` 直达 Step 5（实测）。
5. **排序缺 |Pearson overall|** — ranking 视图排序新增该选项（原有
   display/|charge|/|discharge|/name/family/coverage 保留）。
6. **禁用按钮无原因提示** — Step 3 “下一步: 关系”禁用时加 title 提示
   “先在 Step 1 选择研究目标”。
7. **死代码** — `dataset_family: mode===… ? "SOC" : "SOC"` 无效三元式清除，
   固定 "SOC"（行为不变）。

## C. 逻辑正确性核查（重点确认，未发现漏洞）

- 前端零统计计算：ranking/散点/预览全部后端产出（散点面板明示
  “后端计算，前端不重算”）。
- EXPLORATORY 与 TRAIN_ONLY 不可互串：mode 字符串单向下发，后端对
  TRAIN_ONLY 强制 split_id+fold_index（缺一 INVALID_SPLIT），LEGO 下
  fold 缺失等价全集泄漏，已结构性禁止。
- held-out y 不进入任何 ML-safe 计算（置换不变性测试 R17 保持通过）。
- forbidden predictor（soc_dod_percent 等）在 ranking 与 dataset 两条路径
  都不可进入（BLOCKED_FORBIDDEN_PREDICTOR / roles.py）。
- SOH 不做 frame 级相关（cycle 分组摘要）；Temperature 全 null 无假数。
- 本次新增/修改未触及 feature/TOF/SOC/split/model 算法模块。

## D. 已知限制（如实记录，未伪装成已解决）

- Step 4 的 ranking 恒为 EXPLORATORY（ML-safe 视图在 Step 5）——按设计。
- 特征目录有搜索框但无 family 过滤器（低风险，留待后续）。>12 特征时后端
  截断为 12，UI 现已显式提示（`ranking-cap-note`）。
- fold 选择器仅在存在 split 时出现；创建 split 仍需去
  Advanced → Dataset Split（有链接直达）。
- 电压/电流作为建模目标同样被数据集守卫拦截（仅 SOC 族物化）。

## 验证

- 新增 `tests/integration/test_flow_flexibility_guards.py` 6 项全过；
  全量后端 pytest / ruff、前端 vitest 262 / tsc / eslint 见提交说明。
- 浏览器实测：fold 切换、SOH 提示、构建拦截、深链、|Pearson| 排序。
