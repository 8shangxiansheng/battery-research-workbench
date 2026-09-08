# RELEASE NOTES — Battery Research Workbench v1.0

**发布范围**: BRW-003 → BRW-028（科学核心 → API → UI → Agent → 最终验收）

## 科学能力

- **超声特征库（BRW-013/013X）**: 33 个 MATLAB 对齐统计特征（TD 19 + FD 14），
  独立手算 golden 全过；TDK/TDV 保持 MATLAB parity-pending；频谱 y 语义显式
  （SpectralTransformDefinition，不猜）
- **物理/闸门局部特征（V2.1）**: Bottom-wave Amplitude / SWA / Surface–Bottom
  XCorr TOF（tof_samples=-lag 契约）/ Attenuation 1–4（第 5 特征
  SOURCE_FORMULA_INCOMPLETE 保持 BLOCKED）/ BPS（固定首帧参考）
- **闸门标定（V2.2）**: 24–40 帧 target-blind 确定性标定 + freeze/provenance +
  配置变更重标定 + FeatureGateBindingRegistry
- **特征-状态相关**: SOC Pearson/Spearman（Overall/Charge/Discharge/By-Cycle，
  充放滞回可见）、Temperature INSUFFICIENT_VARIATION、SOH cycle 级摘要
  （2 状态 NOT_READY）；无 naive p-value
- **ML 安全**: Grouped Split → TRAIN-only selection → lock → held-out；
  Random Frame Split 禁止；SOURCE_MOVMEAN5 exploratory-only；held-out target
  不可访问

## 工作台

- Target-first 6 步工作流（Target/Alignment/Features/Relationships/Selection/
  Dataset）
- 同步对齐 UI（3999/3995/4 计数 + provisional 语义 + 行级 provenance）
- Waveform 物理特征卡 + 电气状态面板 + 标定流程
- Report JSON/MD/HTML，numeric claims 带 evidence_ref，machine-readable
  limitations

## Research Assistant（BRW-027R）

- 语义 intent 路由（14 intents）+ AgentResearchSession 持久化
- 全部科学数值经 ToolGateway → WorkbenchService → 确定性核心；Agent 不计算科学
- ClaimGuard（true SOC / Ground Truth / cross-battery / production-ready 阻断）
- Dummy-first 解读；WAITING_FOR_USER → submit → resume same run

## 已知限制（如实声明）

- 单电池 2 循环演示数据；模型未跑赢 Dummy（科学结论）
- Temperature 无通道（CELL_001）；TOF 物理时间 blocked
- provisional timebase（validated_sync=false）
- 33 特征中 TDK/TDV 待 MATLAB parity fixture

## 验收状态

RAW-TO-REPORT E2E / SCIENTIFIC INTEGRITY / REPRODUCIBILITY / AGENT WORKFLOW /
VISUAL DEMO / ARTIFACT INTEGRITY — 全部 PASS（详见 BRW-028 最终报告）。

## 不兼容变更

无（全部 additive；历史 artifacts 不变）。
