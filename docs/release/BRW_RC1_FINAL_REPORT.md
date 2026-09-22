# BRW-RC1 SCIENTIFIC WORKBENCH RELEASE CANDIDATE REPORT

逐项回答（证据索引：docs/reviews/BRW-RC1-r1-inspection-report.md、BRW-RC1-r2-manual-acceptance.md、docs/release/*、docs/ui/screenshots/brwrc1/*）：

1. Is RC1 tied to one exact commit? **YES** — base `3a8a1af7813965d9b9912e70947794e645ab1bf3`（main），RC1 收口以单一 release commit 冻结；manifest 记录 base + 工件身份。
2. Are raw checksums unchanged? **YES** — 2026-09-21 重算与 R1 一致（电气 `8536d395…`、超声 `8e196837…`）。
3. Is final ParameterSet identified? **YES** — PS::3b512b82b40c78c8d264892c（50 MHz USER_SUPPLIED/VERIFIED，注册表来源，无 hardcode）。
4. Is final experiment GateCalibrationRecord identified? **YES** — GC-TOF::e401fecb29ae2c91d511900f，FROZEN v20，experiment-specific，含 gates/frames/diagnostics/确认溯源。
5. Is canonical TOF manually verified? **YES** — 5 帧波形级 Hilbert 包络独立复算 5/5 一致；公式 tof_us=samples/fs×1e6 不变；3995/3995 VALID。
6. Are ambiguous events preserved? **YES** — 4 条 ambiguous（candidate_count=3 等）保留、identity null、不自动择近。
7. Is composite electrical identity spot-checked? **YES** — 随机 20 条 (asset_id, locator) 回源 20/20。
8. Can MeasurementEvent be traced raw→feature→Target? **YES** — 5/5 完整链（frame→ME→feature→electrical record→Reference SOC）。
9. Does Overview honestly summarize experiment state? **YES** — 截图 01/02；unknown 不猜；数值与工件一致。
10. Is Reference SOC semantics correct? **YES** — “回顾性分段归一化参考标签 — 非真实 SOC”全文一致（UI+Agent+报告）。
11. Can selected X + exactly one y be inspected before build? **YES** — feature-label-preview（X 含 canonical tof_us；唯一 y；grain=ME；排除分解；PREVIEW::a1eb1817…）。
12. Is held-out y server-redacted pre-lock? **YES** — 响应体证据：HELD_OUT target=null + y_redacted=true（后端遮蔽，非 CSS）。
13. Does final Dataset match confirmed Preview spec? **YES** — DS::83013a61b316f3489093b358：3995 行、6 预测量含 tof_us、TOF 溯源入 manifest、经正式 run + 用户确认门。
14. Is grouped Split leakage-safe? **YES** — SPLIT::23ebb24f LOGO/CYCLE；held-out 禁用于模型选择；无 Random Frame Split。
15. Are current model metrics reproduced from artifacts? **YES** — model_comparison.json：Dummy 30.72/Linear 35.73/Ridge 35.73/RF 45.92/GB 46.65 %MAE（fold1 有限评估）。
16. Is Dummy-first interpretation preserved? **YES** — “没有模型跑赢 Dummy——科学结论，不是处理故障”（UI/报告/Agent 一致）。
17. Is model/canonical-TOF freshness explicit? **YES** — 当前模型使用当前 canonical TOF（数据集溯源）；旧链保留为 LEGACY，未被替换。
18. Does report avoid retraining? **YES** — 报告收集器只读聚合；Agent 明示“不会重新训练”。
19. Are numeric report claims evidenced? **YES** — result/evidence registry 逐项工件引用；REPORT::5b6cf84d。
20. Does Agent correctly explain TOF/X-y/model/evidence/limitations? **YES** — 10 对话全过（含修正后的 WHAT_NEXT 与 MODEL_TOF_FRESHNESS；held-out 拒绝；ClaimGuard）。
21. Can full workflow be manually traversed? **YES** — Overview→…→Report 截图 + 走查；发现并修复 /analysis 白屏（data router）真实 blocker。
22. Are stale/legacy artifacts distinguished? **YES** — freshness 全 CURRENT；LEGACY/SUPERSEDED 旧链完整保留并标记。
23. Can RC1 reproduce raw→report from fresh root? **YES** — Run A：counts/IDs 与 canonical 全等；fresh-root canonical TOF 3995 VALID（fs 经官方 MISSING_SAMPLING_RATE 通道）。
24. Does same-spec rerun reuse? **YES** — Run B：DATASET/SPLIT/SOC_MODELING REUSED，无重复拟合。
25. Are read-only interactions artifact-immutable? **YES** — 200 工件前后 SHA256 零变化（UI/API/Assistant 只读遍历）。
26. Do final screenshots prove real system behavior? **YES** — 20 张真实前端运行截图（1440/1920），含 ML-safe/stepper/报告/助手。
27. Are Demo and Thesis handoff complete? **YES** — RC1_DEMO_RUNBOOK.md + THESIS_HANDOFF/FIGURE/TABLE INVENTORY。
28. Are limitations honest? **YES** — 11 项机器可读限制 + unsupported claims 禁止清单；单 fold 评估如实说明。
29. Is release state clean? **YES** — 全套测试门通过（见下），worktree 于 RC1 commit 后 clean。

## Test gate
- backend pytest：全量通过（RC1 后复跑，见 §门记录）；ruff clean；git diff --check clean；mypy 受限于 numpy stub 对 py3.13 的 `Type statement`（环境项，记录）。
- frontend：tsc clean、eslint clean、vitest 248 passed/1 skipped、vite build 成功。
- clean-room：Run A/B 如上。

## 结论

BRW-RC1 COMPLETE
RELEASE CANDIDATE FREEZE PASS
MANUAL SCIENTIFIC ACCEPTANCE PASS
RAW-TO-REPORT REPRODUCTION PASS
CANONICAL TOF PASS
FEATURE-LABEL WORKFLOW PASS
ML-SAFE EVALUATION PASS
WORKFLOW CONTINUITY PASS
AGENT ASSISTANT PASS
DEMO HANDOFF PASS
THESIS HANDOFF PASS
ARTIFACT INTEGRITY PASS

建议：tag `brw-rc1`（远程发布需维护者批准；不自动创建 BRW-RC2）。
