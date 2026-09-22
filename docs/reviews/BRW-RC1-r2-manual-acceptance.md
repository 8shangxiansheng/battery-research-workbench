# BRW-RC1 — R2 Manual Acceptance Evidence Log

Reviewer: Qoder agent · started 2026-09-21 · state root `data/processed` · API sandbox :8973 (real root)

## Identity / freeze
- RC candidate base commit: `3a8a1af` (pre-R2). RC1 release commit pending at end.
- Raw SHA256 recomputed 2026-09-21 (see r1 report §2); electrical 小-1-1-264.xlsx `8536d395…`, ultrasound export txt `8e196837…` — unchanged vs R1 recompute.
- Canonical experiment: CELL_001/EXP_001 ✔.
- Final ParameterSet: **PS::3b512b82b40c78c8d264892c** — ultrasound.sampling_rate_hz = 50 MHz, USER_SUPPLIED, VERIFIED (from registry, not hardcoded) ✔ §F.
- Final GateCalibrationRecord: **GC-TOF::e401fecb29ae2c91d511900f** — EXPERIMENT-specific, FROZEN, version 20, user-confirmed, surface/bottom gates + calibration frames + diagnostics ✔ §G.

## §H Canonical envelope-peak TOF — waveform-level manual check (5/5)
Independent recomputation from `waveforms.zarr` (Hilbert envelope, gate windows from GC record):
| frame | surface (recomp/artifact) | bottom | tof_samples | tof_us | verdict |
|---|---|---|---|---|---|
| 0 | 97/97 | 873/873 | 776 | 15.5200 | OK |
| 1 | 97/97 | 875/875 | 778 | 15.5600 | OK |
| 2 | 97/97 | 873/873 | 776 | 15.5200 | OK |
| 3 | 97/97 | 873/873 | 776 | 15.5200 | OK |
| 4 | 97/97 | 873/873 | 776 | 15.5200 | OK |
Formula preserved: tof_samples = bottom−surface; tof_us = samples/fs×1e6 ✔. Artifact now VALID 3995/3995 (was PARTIAL 0-valid pre-R2 via RUN::20260921T062203244439Z-cc09aef0, force-recompute of CANONICAL_TOF_FEATURES only — all upstream REUSED).

## §I Real TOF summary (current artifact)
rows 3995 · valid 3995 · tof_samples 776–804 (median 798) · tof_us 15.52–16.08 µs (median 15.96) · edge hits: see canonical_tof_audit.json · fs from ParameterSet (verified) ✔.

## §J Synchronization / identity
- unique matches 3999 frames; ambiguous preserved: **4 events** with candidate_record_count>1 (ME U001::691, +3) — retained, electrical identity null, never auto-nearest ✔.
- sync_error_s persisted ✔; validated_sync=false / timebase PROVISIONAL ✔ (honest).
- Composite identity spot check: random 20 (electrical_asset_id, electrical_record_locator) → records.parquet **20/20** unique hit, asset match ✔.

## §K MeasurementEvent traces (5/5)
frame→ME→feature→electrical record→Reference SOC, e.g. ME::…::0: V=3.383 · abs-peak amp=27757 · tof_us=15.52 · target=0.00; all 5 rows composed end-to-end from canonical artifacts ✔.

## §L/§O Overview + Target semantics
- /targets: reference_soc_percent = “参考SOC”, semantic_type DERIVED_REFERENCE_LABEL, retrospective — never labelled True SOC ✔ §O.
- Overview UI walk: pending browser pass (screenshot 01/02).

## §M Sampling resume — isolated fixture
covered by unit suite (BRW-018R2) + live probe: run-less submissions no longer create false WAITING dead-ends; resume path exercised in clean-room below. (Isolated fixture demo scheduled with screenshots.)

## §P/§Q Feature catalogue + demo X / one y preview
- Catalogue: 33 TD/FD codes (31 golden-passed) + physical codes + canonical TOF now selectable (`tof_us` code served read-only from artifact).
- Demo X = tof_us, amplitude_a_u, SWA, BPS, waveform_p2p_a_u, waveform_mean_a_u; y = Reference SOC (exactly one) — preview 200 ✔
  - grain: one row = one eligible MeasurementEvent ✔ · spec_hash PREVIEW::16d6c38dd43166f05855c818 · summary: 3999 aligned / eligible rows counted / excluded_by_reason {AMBIGUOUS_SYNC:4, FEATURE_MISSING:3, ANALYSIS_INELIGIBLE:4} ✔
  - tof_provenance: SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1 0.3.0 · fs 50 MHz verified (PS::3b512b82) · GC-TOF::e401fecb EXPERIMENT_CONFIRMED ✔
- ambiguous excluded row inspected: ME::…::691 — electrical_identity null, target null, candidate_count 3, explicit reason ✔ §R.

## §S/§T Exploratory vs ML-safe + held-out protection
- Exploratory preview (no split): preview_state=PREVIEW_DRAFT, all y visible, flagged not-ML-safe.
- ML-safe review bound to SPLIT::23ebb24f fold1: redaction_summary train 1903 / held_out 2092, policy “HELD_OUT y redacted server-side before serialization”.
- Network-level proof (raw JSON response body): all 20 sampled HELD_OUT rows target=**null** + y_redacted=true, X values present ✔ (verified on response payload, not DOM).

## §U/§V/§W Final chain (materialized via official FULL_PRE_MODEL runs)
- Dataset **DS::83013a61b316f3489093b358** — 3995 rows, predictors = demo X (6), target soc_reference_percent, PS::3b512b82, manifest carries tof_method_id/tof_definition_version/tof_gate_calibration_id/tof_parameter_set_id/canonical_tof_valid_rows=3995 ✔ §U.
- Split **SPLIT::23ebb24fe8e7732fac780dde** — LEAVE_ONE_GROUP_OUT, unit CYCLE, WITHIN_BATTERY_CROSS_CYCLE, held-out forbidden for model selection; no Random Frame Split offered anywhere ✔ §V.
- Models (fixed suite, no tuning): Dummy 30.721 · Linear 35.725 · Ridge 35.733 · RF 45.918 · GB 46.648 %MAE (fold1 limited evaluation, metrics read from model_comparison.json artifact) → **no model beat Dummy** ✔ §W (not a blocker).
- §X freshness: current model DOES use current canonical envelope-peak TOF (dataset predictors + provenance); legacy chain (DS::6a3142e5 / REPORT::62c70630) preserved untouched as LEGACY/SUPERSEDED ✔.
- Report **REPORT::5b6cf84d27d20a880c914506** JSON+MD+HTML under data/artifacts/…/reports/ — bound to new chain (latest_canonical + result registry DS::8301…), limitations list drops TOF_UNAVAILABLE_OR_BLOCKED (verified canonical provenance present), no-retrain collector path ✔ §Y.

## §AB Freshness audit (live workflow-context)
dataset/models/report = CURRENT · all 8 steps COMPLETE · current_step REPORT · recommended OPEN_REPORT · pending_action null ✔.

## R2 code deltas (wiring/evidence only, no new science)
features_v2: tof_us selectable (read-only artifact) + rms/envelope aliases; physical-features canonical TOF block.
orchestrator: DATASET optional-dep on CANONICAL_TOF_FEATURES + tof_us join + manifest TOF provenance.
collector: latest-evaluated-chain resolution (was hardcoded legacy IDs) + TOF limitation conditional on real provenance.
research_overview: dynamic current-chain dataset (was hardcoded DS::6a3142e5) + TOF-provenance freshness criterion.
workflow_context: run-less submissions no longer fake WAITING_FOR_USER.
frontend: tof_us feature chip.
Tests updated to RC1 reality (chain ids, 5-model suite, redaction fold names) — no assertion weakened; stale-chain scenario now constructed in-sandbox (W21) instead of incidental.

## §AD/AE Clean-room (Run A / Run B) — PASS
Run A: fresh root /tmp/brw-rc1-clean via official PipelineOrchestrator FULL_PRE_MODEL; all deterministic stages SUCCEEDED; counts {frames 3999, ME 3999, ambiguous 4, eligible 3995, labels 3999, soc_valid 3995} == canonical; first/last ME ids identical; canonical TOF in fresh root: 3995 VALID @ fs 50 MHz VERIFIED (fresh PS::091640ea… via official MISSING_SAMPLING_RATE user action → same-run resume).
Run B (same spec): DATASET/SPLIT/SOC_MODELING **REUSED** (no re-fit); re-executed = deterministic re-hash stages only. Same-spec reuse ✔.

## §AF Read-only invariance — PASS
200 artifact files SHA256 before/after reading Overview/preview×2/models/report/assistant evidence/canonical-tof/physical-features endpoints: 0 changes.

## §Z Agent 10 conversations — PASS (2 routing gaps fixed in R2)
Session RS::b3ed85409892. Highlights: SELECT_TARGET disclaimer (参考SOC 非真实 SOC); TOF explanation cites artifact method+PS+GC (no guessing); 3995 rows explained via alignment exclusions; model answer uses CURRENT artifact numbers (Dummy 30.72, “科学结论不是处理故障”); HELD_OUT request refused structurally (“后端封锁 y，非界面隐藏”); report generation states 不重新训练; evidence lists artifact refs; typed navigation present.
Fixed gaps (planner wiring only):
- MODEL_TOF_FRESHNESS intent → answers “是——数据集 DS::8301… 预测变量含 canonical tof_us（方法/gate/PS 溯源）”.
- WHAT_NEXT intent → consumes workflow-context recommended_next_action (single source of truth, §52): “当前步骤 REPORT，推荐：查看研究报告” + typed OPEN_REPORT nav.

## §M/§N isolated resume & gate UI
Isolated-fixture sampling-missing→Saving→Saved→same-run resume + readiness refresh is exercised by the BRW-018R2/025R-WF regression suites (run in full test gate below); official clean-room MISSING_SAMPLING_RATE path additionally exercised in Run A. Gate calibration UI verified against frozen GC-TOF::e401fecb (browser walkthrough screenshots 04).
