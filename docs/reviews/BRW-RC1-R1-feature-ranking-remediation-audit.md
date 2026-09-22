# RC1-R1 — Feature Ranking Remediation Audit (BRW-021R2)

Scope (per task pack §31 / 12_RC1_R1_REMEDIATION): ONLY the Relationships
primary path that RC1 manual visual acceptance found broken. No unrelated
scientific modules were reopened. Feature/TOF/SOC/split/model **algorithms**
were not modified — only the ranking API surface, its DTOs, the workbench
view, and agent plumbing.

## Original defect

- `POST /api/v1/experiments/CELL_001/EXP_001/feature-target-ranking`
  with `tof_us` in `features` → `404 NOT_FOUND "unknown features: ['tof_us']"`
  (request_id 012b24ef1b414607, captured live). UI rendered 无法加载此视图.
- Root cause: RC1 added `tof_us` to the *preview* vocabulary but not the
  *ranking* allowlist. Deeper latent defect found while fixing: the legacy
  `TRAIN_ONLY_ML_SAFE` ranking mode ignored `split_id`/`fold_index` entirely,
  so "ML-safe" rankings silently included held-out rows.

## Re-verification matrix

| # | Item | Result | Evidence |
|---|------|--------|----------|
| 1 | Relationships route/load | PASS | Step 4 renders table with 4 rows after Rank features (browser, live); `test_r01` pins the exact failing request as 200 with real coefficients |
| 2 | Ranking API | PASS | ranking v2: Pearson+Spearman × overall/charge/discharge, n_valid/n_missing, direction_status enum, freshness/commit_eligible per entry (R04–R09, R21–R25) |
| 3 | Target-conditioned analysis | PASS | SOC stratified suite; SOH cycle-summary-only; Temperature UNAVAILABLE without fake numbers; voltage/current direct branch (R02, R11, R24, R25) |
| 4 | Selection handoff | PASS | ranking checkboxes → features + `selection_source` (EXPLORATORY_RELATIONSHIP_RANKING / TRAIN_ONLY_RELATIONSHIP_RANKING); Select never auto-builds/trains (browser walkthrough; vitest selection spec) |
| 5 | Feature–Label Preview parity | PASS | committed ranked codes == Preview X columns, row `values` keys identical (`test_r26`) |
| 6 | Workflow continuity | PASS | steps 1–6 unchanged elsewhere; invalidateWorkflow/preview chain intact (full vitest suite 262 pass; M05 guard upgraded to the stronger split+fold-pointer contract) |
| 7 | Agent ranking intent | PASS | session chat produces EXPLORATORY ranking with 非 ML-safe wording (R29); ML_SAFE w/o split → SCIENTIFIC_BLOCK (R30); with split → TRAIN-only fold-scoped answer (R31); tool cannot bypass structural guard (R32) |
| 8 | Artifact integrity | PASS | sha256 of events/labels/canonical-TOF/dataset/split/models identical before/after exploratory+ML-safe+detail ranking gauntlet (`test_r28`) |

## Structural ML-safe findings fixed in this pass

1. `TRAIN_ONLY_ML_SAFE` now **requires split_id AND fold_index** — with
   leave-one-group-out, the union of all folds' TRAIN rows is the full
   dataset, so a fold restriction is structural, not cosmetic (R15).
2. TRAIN membership is applied to the correlation input **before** any
   statistics run; held-out y is never loaded (R16/R17).
3. Held-out permutation invariance proven by shuffling held-out SOC values
   in-process: TRAIN-only ranking byte-identical; control exploratory
   ranking does move (R17).
4. NaN feature values (e.g. the 4 frames without VALID canonical TOF) are
   now counted as missing instead of poisoning Pearson (NUMERICAL_NAN) and
   Spearman ranks; tof_us Pearson is a real 0.164 on 3992 pairs.

## Canonical TOF provenance honesty

- Provenance reports BOTH the GateCalibrationRecord embedded in
  `canonical_tof.parquet` (GC-TOF::1f8cac37…, v22 — the source of the
  values) and the newest confirmed record (GC-TOF::1c246f22…, v26), plus a
  window-match verdict. Current windows are identical →
  `gate_calibration_refresh_required = false`; if a future freeze changes
  the gate windows the tof_us row flips to REFRESH_REQUIRED and loses
  commit eligibility.
- Legacy GC-TOF::e401fecb (RC1 §G record) remains on disk untouched; the
  RC1 docs were written before today's additional gate re-confirmations
  advanced the version chain v21→v26. No artifact was rewritten by this
  task (R28).
- `TOF_XCORR` is kept as a diagnostic row flagged `legacy_diagnostic`, never
  a substitute for `tof_us` (R13).

## Deviations / notes

- `direction_dependent` boolean retained as a derived alias of
  `direction_status == DIRECTION_DEPENDENT` so pre-existing R-series
  assertions (BRW-018/028 suites) keep their meaning.
- The planner's ML_SAFE branch was dead code (nothing ever set
  `feature_selection_mode="ML_SAFE"`); `_on_create_grouped_split` now flips
  it once a split exists, matching its own "下一步 TRAIN-only 特征选择" copy.
- Screenshot states 16 (stale/REFRESH_REQUIRED) reflect whatever the live
  data genuinely shows; no state was fabricated for the shoot.

Verdict: **RC1-R1 FEATURE RANKING REMEDIATION PASS**
