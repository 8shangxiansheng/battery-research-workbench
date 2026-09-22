# BRW-021R2 — Round 1 Inspection Report (inspect only, no code changes)

Date: 2026-09-22 · Stack: API :8000 + UI :5173 against RC1 frozen state (commits e0666e4 + f1f908e, worktree clean at start)

## 1 Exact failing request
`POST /api/v1/experiments/CELL_001/EXP_001/feature-target-ranking`
body `{"target_id":"reference_soc_percent","features":[<draft selection>,"tof_us",…],"mode":"EXPLORATORY"}`
(from Relationships/Step 4 `Rank features` button, `FeatureRankingTable` useMutation, frontend/src/components/workbench/FeatureTargetWorkbench.tsx:24-28).

## 2 HTTP / error (reproduced live)
`HTTP 404 {"error":{"code":"NOT_FOUND","message":"unknown features: ['tof_us']","request_id":"012b24ef1b414607"}}`
Control: same endpoint with `["amplitude_a_u","SWA","BPS"]` → 200 with real coefficients. Endpoint itself healthy.

## 3 Frontend state error
`rank.error` → generic `ErrorState` “无法加载此视图” (shared.tsx:17) — one blanket message for all failures (§22 requires typed states). Retry re-fires the same mutation (real refetch OK) but will deterministically re-fail while tof_us ∈ selection.

## 4 Backend root cause
`feature_target_ranking` allowlist (features_v2.py:1516): `known_codes = physical ∪ catalogue  _ALIAS_TO_RAW`. RC1 added `tof_us` to the **preview** allowlist + physical-features + dataset join, but **not** to the ranking vocabulary. Since RC1, `tof_us` appears as a selectable chip (AnalysisWorkbench PHYSICAL_FEATURES), so any draft selection containing canonical TOF 404s the ranking → “无法加载此视图”. Classic partial-vocabulary migration.

## 5 Artifacts exist?
Yes. canonical_tof.parquet 3995/3995 VALID (SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1 0.3.0, fs 50 MHz VERIFIED PS::3b512b82, GC-TOF::e401fecb FROZEN v20); events/labels/frames all CURRENT per RC1 freshness audit.

## 6 Stale identity involvement?
Not for this failure. But ranking has **no freshness/stale concept at all** (§11 REFRESH_REQUIRED missing); legacy TOF_XCORR is rankable with no “diagnostic-only, not canonical” marker (§10).

## 7 DTO/schema mismatches (current vs §3/§5/§8/§18)
- Missing per row: `n_missing`, `spearman_charge/discharge` (only pearson_*), family, units, zh name, current/legacy, selection state, evidence/producer/freshness envelope.
- `direction_dependent` is a boolean heuristic |Δpearson|>0.3; §5 requires 5-way enum (SAME_DIRECTION/DIRECTION_DEPENDENT/WEAK_ASSOCIATION/INSUFFICIENT_VARIATION/UNAVAILABLE).
- No ranking envelope fields (mode/scope/ordering/limitations/evidence/freshness).
- Real data proves §8 hazard: amplitude_a_u overall Pearson 0.043 / Spearman −0.134 but charge +0.477 vs discharge −0.565 — abs(overall) ranking would bury a strong direction-dependent relation.

## 8 Canonical TOF migration involvement
Yes — direct cause (§4). Also §10 provenance display (fs + GateCalibrationRecord + coverage 3999 vs 3995) absent from ranking rows.

## 9 ML-safe structural gap (more serious than the 404)
`mode=TRAIN_ONLY_ML_SAFE` only changes meta text. The endpoint **ignores split_id/fold_index entirely** (client never sends them; server never filters) → “ML-safe ranking” currently computes on ALL eligible rows including held-out fold targets. Violates §12/§13/§16 until fixed: TRAIN rows must be the only input (structural, not post-filter).

## 10 Minimum remediation plan (R2, no algorithm changes)
1. Backend ranking v2 in features_v2.py: accept `tof_us` (read-only canonical artifact join like preview) + `split_id`/`fold_index`; TRAIN-only = restrict rows to fold TRAIN membership **before** correlation; return enum direction status, n_missing, charge/discharge spearman, family/units/zh, freshness/stale flags, alias dedup (amplitude_a_u≡waveform_abs_peak_a_u), forbidden-predictor BLOCK, SOURCE_MOVMEAN5 exploratory-only, no fake numbers for UNAVAILABLE.
2. DTO additions in client.ts + FeatureRankingTable: full column set, view sorting (abs overall/charge/discharge spearman, name, family, coverage), select/bulk-select handoff to Step 5 with `selection_source` provenance (EXPLORATORY_RELATIONSHIP_RANKING / TRAIN_ONLY_RELATIONSHIP_RANKING + split/fold), no auto build/train.
3. Error states: typed error mapping (RELATIONSHIP_ARTIFACT_MISSING/STALE_ANALYSIS/API_UNAVAILABLE/TARGET_NOT_READY/NO_ELIGIBLE_FEATURES/INVALID_SPLIT/UNEXPECTED_ERROR), “Ranking…” busy state, retry = invalidate+refetch.
4. Feature detail relationship plot panel (backend-provided scatter points + stats; frontend never computes correlation).
5. Agent: ranking intent (RANK_CANDIDATE_FEATURES already routes) must pass workflow-context mode; held-out-y request → SCIENTIFIC_BLOCK (existing guard pattern).
6. Tests R01–R38 + E2E A–K + 20 screenshots + hash invariance + RC1-R1 remediation audit.

## 11 Affected artifacts
None scientific. Writes limited to: code (features_v2.py, client.ts, FeatureTargetWorkbench/AnalysisWorkbench), selection/audit state on commit, tests, docs, screenshots. Raw/sync/ME/features/dataset/split/models/report untouched (ranking read-only).

## 12 Regression plan
Keep RC1 invariants: preview endpoint untouched; dataset/split/model chain hash-checked before/after; existing ranking tests (test_api_resources correlations suite) must still pass; BRW-025R-FE-R2/WF suites green; no changes to correlation module math (reuse soc_correlation_suite/_pearson/_spearman).
