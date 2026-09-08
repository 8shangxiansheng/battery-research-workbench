# REPRODUCE_FROM_RAW — 从原始数据完整重算

**原则**: 只使用正式 orchestrator / API / CLI；禁止旁路脚本重算科学数值。

## 前置

- raw 资产就位（见 RELEASE_RUNBOOK 数据放置），checksum 校验：
  ```bash
  shasum -a 256 "data/raw/batteries/CELL_001/EXP_001/electrical/小-1-1-264.xlsx"   # 8536d395…
  shasum -a 256 "data/raw/batteries/CELL_001/EXP_001/ultrasound/export - 2024.01.06 - 21.03.01.txt"  # 8e196837…
  ```

## 一键复算（clean-room）

```bash
.venv/bin/python scripts/clean_room_reproduce.py --out /tmp/brw028-clean
```

该命令在 fresh output root 上执行 `FULL_PRE_MODEL` profile（全部 18 个确定性 stage）：

1. **import/parse/QA** — ELECTRICAL_CANONICAL、ULTRASOUND_CANONICAL
2. **timebase** — TIME_ANCHOR、ULTRASOUND_TIMESTAMPS（provisional，unknown timezone 不猜）
3. **synchronization** — SYNCHRONIZATION（validated_sync=false 保持）
4. **MeasurementEvent** — MEASUREMENT_EVENTS（one event = one frame；ambiguous 保留）
5. **analysis slice** — ANALYSIS_SLICE（analysis_eligible_only）
6. **features** — ULTRASOUND_FEATURES（sample-domain）、GATED_FEATURES（canonical gate specs）、TOF_ACTIVATION
7. **labels/parameters** — REFERENCE_LABELS、PARAMETER_SET
8. **feature–label** — FEATURE_LABEL_ANALYSIS（measurement_event_id 粒度）
9. **target/dataset** — DATASET（exactly one target； predictors 显式）
10. **split** — SPLIT（LEAVE_ONE_GROUP_OUT，按 cycle 分组；Random Frame Split 不可用）
11. **ML-safe selection** — FEATURE_ANALYSIS（TRAIN-only；CONFIRM_FEATURE_SELECTION 用户确认）
12. **baselines** — SOC_MODELING（Dummy/Linear/Ridge/RF/GB 固定套件，无 tuning）
13. **report** — SCIENTIFIC_REPORT（JSON + MD + HTML，不重训练）

运行中若出现 `WAITING_FOR_USER`（CONFIRM_FEATURE_SELECTION），runner 会走官方
`submit_user_action → resume_run` 继续同一 run（不旁路）。

## 产出

- `out/reproducibility_manifest.json` — raw checksums、counts、canonical 对比、run/stage states、environment
- `out/artifacts/CELL_001/EXP_001/reports/REPORT::*/scientific_report.{json,md,html}`
- `out/processed/**` — 全部 canonical artifacts

## Run A vs Run B（reuse）

```bash
# Run A（clean）
.venv/bin/python scripts/clean_room_reproduce.py --out /tmp/brw028-clean
# Run B（同 spec 再跑 → 尽可能 REUSED）
.venv/bin/python scripts/clean_room_reproduce.py --out /tmp/brw028-clean
```

预期 Run B：13 个 stage REUSED（canonical artifacts 命中，不重算 feature/model）。

## 与 canonical 对比

manifest 内自动比对：
- canonical counts（frames/events/ambiguous/eligible/labels/soc_valid）一致
- deterministic IDs（首个/末个 measurement_event_id）一致

允许的环境差异（不阻断）：Python patch 版本、numpy/scikit-learn 浮点末位、运行时间戳、run_id。

## 单依赖增量失效（invalidation）

```bash
# 改一个上游依赖（例：selected features），只应失效下游 dependent stages：
# DATASET/SPLIT/FEATURE_ANALYSIS/SOC_MODELING/SCIENTIFIC_REPORT 重新计算；
# raw/parser/sync/features/labels/parameters 保持 REUSED。
```

手动验证：修改 plan 的 `features.selected_features` 再跑同 out 目录 → 观察新 run 的
stage states（上游 REUSED，下游重算）。

## 记录 ID/checksum

每 stage 产出 manifest（`*_manifest.json`）含 artifact_id、producer_version、
input checksums；run manifest（`run_manifest.json`）含 plan_id、全部 node states 与
final_artifacts。
