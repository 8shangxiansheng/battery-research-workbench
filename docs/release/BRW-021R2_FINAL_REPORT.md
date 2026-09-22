# BRW-021R2 — Feature Ranking & Target-Conditional Relationship Report

Date: 2026-09-22 · Experiment: CELL_001/EXP_001 (canonical, RC1 CURRENT chain)
Defect fixed: Relationships / Step 4 "Rank features" → 无法加载此视图.

## Files changed

- `src/battery_workbench/api/routes/features_v2.py` — ranking v2 (rewrote
  `feature_target_ranking`): MeasurementEvent exact join, Pearson+Spearman ×
  overall/charge/discharge, n_valid/n_missing, direction_status enum,
  canonical-tof_us read-only artifact join + honest GC provenance
  (embedded vs current record, window-match → REFRESH_REQUIRED), forbidden
  predictor BLOCK before unknown-check, alias dedup, SOURCE_MOVMEAN5 gate,
  structural TRAIN-only filter (split_id AND fold_index required; TRAIN
  membership applied before any correlation input), detail scatter, typed
  error codes, association-only envelope. NaN series values now counted as
  missing (was silently poisoning Pearson/Spearman).
- `frontend/src/api/client.ts` — FeatureRanking* DTOs extended.
- `frontend/src/components/workbench/FeatureTargetWorkbench.tsx` — full
  rewrite of the ranking table: typed error taxonomy, direction badges,
  sort select, selection checkboxes → provenance callback, backend-computed
  scatter panel, real-refetch retry, tof provenance line.
- `frontend/src/pages/redesign/AnalysisWorkbench.tsx` — ranking⇄selection
  two-way binding, `selection_source` provenance line, fold-aware
  TRAIN_ONLY ranking in Step 5.
- `src/battery_workbench/agent_assistant/{planner,session}.py`,
  `src/battery_workbench/agent_tools/{gateway,registry}.py` — agent ranking
  honors session mode: ML_SAFE requires split (SCIENTIFIC_BLOCK otherwise),
  passes split_id/fold_index structurally, groups-split-ready now flips
  session into ML_SAFE (was dead state); honest TRAIN-only answer copy.
- Tests: `tests/integration/test_brw021r2_ranking.py` (R01–R32),
  `frontend/tests/brw021r2-ranking-table.test.tsx` (14 cases),
  `frontend/tests/guards-target-workflow.test.tsx` (M05 upgraded to
  split+fold-pointer contract), `tests/unit/test_api_resources.py` (display
  ordering migration), `docs/api/openapi-v1.json` (ranking description
  refresh, 1-line diff).
- Docs: `docs/reviews/BRW-021R2-r1-inspection-report.md`,
  `docs/reviews/BRW-RC1-R1-feature-ranking-remediation-audit.md`,
  `frontend/screenshot-brw021r2.mjs`,
  `docs/ui/screenshots/brw021r2/` (20 PNGs + manifest),
  task-pack `15_ACCEPTANCE_MATRIX.md` filled.
- NOT touched: feature/TOF/SOC/split/model algorithms (`state_correlation`,
  `canonical_tof`, `gate_calibration`, `splits/*`, `modeling/*` all reused
  read-only); `data/raw/`; no artifact rewritten (hash-invariance test).

## Behavior changed

Step 4 now loads a real, target-conditional ranking for Reference SOC
(including canonical `tof_us`); ML-safe ranking is structurally TRAIN-only;
selection hands off to Step 5/6 with provenance; the agent answers ranking
questions within the same rules.

## §32 item-by-item (26 questions)

1. Real Relationships page loads? **YES** — live browser: 4 rows, no error state; R01.
2. Original root cause identified/fixed? **YES** — ranking vocabulary lacked `tof_us` (404 request_id 012b24ef…); fixed + regression-pinned.
3. Reference SOC produces real relationship results? **YES** — BOTTOM_AMP Pearson 0.861/Spearman 0.805 on 3995 events.
4. Pearson available? **YES** (overall/charge/discharge).
5. Spearman available? **YES**.
6. Overall/Charge/Discharge available? **YES** — R07; scatter scopes overall 3995/charge 1868/discharge 1588.
7. Direction-dependent identified honestly? **YES** — SWA overall 0.064 but charge +0.38/discharge −0.67 → DIRECTION_DEPENDENT; never demoted by overall cancellation (R09).
8. Canonical TOF current method? **YES** — SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1 0.3.0, fs 50 MHz VERIFIED (PS::3b512b82), GC embedded (1f8cac37 v22) vs current (1c246f22 v26) windows-match shown (R12).
9. Legacy/stale separated? **YES** — TOF_XCORR `legacy_diagnostic`; stale→REFRESH_REQUIRED path implemented, honest false today because windows match; RC1 docs' e401fecb kept on disk (R13, audit §Deviation).
10. Unavailable features without fake ranking? **YES** — Temperature all-null + UNAVAILABLE; NaN tof frames counted missing; no imputation (R11, R06).
11. Relationship plot works? **YES** — backend-computed scatter ≤300 pts, frontend never recomputes (R23, shot 08).
12. Ranked features directly selectable? **YES** — per-row checkbox, commit_eligible gating (shots 10/11).
13. Selection provenance Exploratory vs ML-safe? **YES** — `selection_source = EXPLORATORY_RELATIONSHIP_RANKING | TRAIN_ONLY_RELATIONSHIP_RANKING` rendered Step 5 (shot 11).
14. Selection→Preview exact parity? **YES** — ranked codes == Preview X columns and row value keys (R26).
15. ML-safe requires grouped split? **YES** — INVALID_SPLIT without split_id AND fold_index; UI links to Dataset Split (R15).
16. ML-safe ranking uses TRAIN-only targets? **YES** — fold1 n=1903 / fold2 n=2092 = TRAIN∩eligible, verified against artifacts (R16/R18, shots 13/14).
17. Held-out target absent? **YES** — TRAIN membership filters rows before any y is read; HELD_OUT redaction notice in shot 15.
18. Held-out permutation invariant? **YES** — R17: shuffling held-out SOC leaves TRAIN-only ranking byte-identical while exploratory moves (control).
19. Fold-specific rankings preserved? **YES** (R18).
20. Forbidden predictors blocked? **YES** — soc_dod_percent → BLOCKED_FORBIDDEN_PREDICTOR, never ranked/committed (R20).
21. SOURCE_MOVMEAN5 exploratory-only? **YES** — exploratory_only badge + commit_eligible false; TRAIN_ONLY request → SCIENTIFIC_ACTION_REQUIRED (R22).
22. Retry real refetch? **YES** — mutation.mutate() real POST; abort→error→retry→rows (shot 18, vitest retry spec).
23. Agent ranking respects ML-safe rules? **YES** — R29–R32: exploratory wording, SCIENTIFIC_BLOCK without split, TRAIN-only fold answer, no bypass at tool level.
24. Read-only ranking artifact-immutable? **YES** — sha256 of 7 key artifacts unchanged across the gauntlet (R28); full backend pytest gate exit 0.
25. Screenshots prove real success? **YES** — 20 real shots with per-shot DOM assertions + manifest; 14/15/16 substitutions documented honestly (fold2 reached via real matcher, HELD_OUT redaction as leakage-block evidence, 诊断量 badge as the only reachable staleness affordance) — nothing fabricated.
26. RC1-R1 remediation pass? **YES** — docs/reviews/BRW-RC1-R1-feature-ranking-remediation-audit.md, all 8 re-verification items PASS.

## Test runs

- Backend: `pytest` full suite exit 0, incl. new R01–R32 (26 tests) and
  `ruff check src tests` clean.
- Frontend: `vitest run` 262 passed / 1 skipped (19 files) incl. new 14
  ranking-table cases; `tsc --noEmit` clean; `eslint --max-warnings 0`
  clean; production build OK.
- Browser E2E A–K: walked live (A table load, B/C TOF detail+scatter,
  D selection→provenance, E fold TRAIN-only n, G refresh-verdict line,
  H temperature, K agent EXPLORATORY answer) + screenshot script for the rest.

## Known limitations

- Held-out-permutation proof patches the loader in-process (structural
  filter is the mechanism; disk artifacts are never modified).
- No UI fold picker in Step 5: ML-safe ranking follows the ready analysis'
  fold; fold2 evidence shot reaches a real fold2 analysis via catalogue
  match (manifest 14).
- Ranking display order is |Spearman overall| by design and labeled as a
  display ordering, not a scientific "best".
- Session `ranking_fold` defaults to fold1 when the agent flow has not
  chosen one; the answer states this limitation.

## Declarations

BRW-021R2 COMPLETE · FEATURE RELATIONSHIP LOAD PASS · TARGET-CONDITIONAL
ANALYSIS PASS · DIRECTION-AWARE RANKING PASS · EXPLORATORY RANKING PASS ·
ML-SAFE RANKING PASS · SELECTION HANDOFF PASS · FEATURE-LABEL PREVIEW
PARITY PASS · RC1-R1 FEATURE RANKING REMEDIATION PASS
