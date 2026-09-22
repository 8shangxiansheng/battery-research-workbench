# BRW-RC1 — Round 1 Inspection Report (no code changes)

Date: 2026-09-21 · Inspector: Qoder agent · Mode: §B First Inspect only

## 1. Candidate commit / worktree
- Branch `main`, candidate commit `3a8a1af` (feat(BRW-025R-WF)…).
- Worktree clean at inspection start (0 modified, 0 untracked).
- API verified healthy (`/api/v1/health` → ok) against the real state root `data/processed/`.

## 2. Raw assets / checksums (recomputed SHA256, 2026-09-21)
| File | SHA256 |
|---|---|
| CELL_001/EXP_001/electrical/小-1-1-264.xlsx | `8536d3959db6efc73cdbc30903b33f8c6a429385663597832e4d918459dbc608` |
| CELL_001/EXP_001/ultrasound/export - 2024.01.06 - 21.03.01.txt | `8e196837bf13637d4c0d2244a403c018b3bbd81b5b1b81ac5c08df2007be5acb` |
| CELL_210/EXP_015+016 sample_electrical.xlsx | `2fd9c12d…24eb11` (identical fixture pair) |
| CELL_210/EXP_015+016 sample_ultrasound.txt | `1a5afbce…d9679a` (identical fixture pair) |
- `data/raw/manifests/data_assets.csv` records asset→path mapping but **no checksum column**.
- BLOCKER-adjacent finding: `.DS_Store` files exist inside `data/raw/batteries/` (3 occurrences). Raw is supposed to be immutable/clean; needs decision (leave as OS noise vs. document).

## 3. Current ParameterSet
- 4 ParameterSets on disk; the fs-verified one is **PS::3b512b82b40c78c8d264892c** — `ultrasound.sampling_rate_hz = 50 MHz`, status RESOLVED, verification VERIFIED, source USER_SUPPLIED, record `ultrasound.sampling_rate_hz:USER_SUPPLIED:EXPERIMENT:10000`.
- API `/parameters` confirms this as effective. 50 MHz comes from the parameter registry (user submission chain), not hardcoded. ✔ for §F.
- PS::9ebbb833dfac3cf1cc9da8bc = older set used by the CURRENT model dataset (parameter_dependency INFORMATIONAL).

## 4. Current GateCalibrationRecord
- **GC-TOF::e401fecb29ae2c91d511900f** — status `FROZEN`, version 20, experiment-specific (CELL_001/EXP_001), confirmed by user; has surface/bottom gate ids + sample ranges + calibration_frame_ids. ✔ for §G identity.
- 3 other GC-TOF records exist (earlier versions) — superseded, must be classified LEGACY/SUPERSEDED in the audit.
- Gap: GET `/experiments/…/tof-gate-calibration` (default params) returned an error `detail` — must check the endpoint's expected query (version/frame) during R2.

## 5. Current canonical TOF artifact
- `features_physical/CELL_001/EXP_001/canonical_tof.parquet` (method SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1, def v0.3.0): 3995 rows, **all `tof_status=PARTIAL`**; `tof_samples` present (776–804, median 798); `tof_us` **all null**; manifest: `sampling_rate_hz: null, sampling_rate_verified: false, canonical_tof_valid: 0`.
- A separate `ultrasound_tof.parquet` (arrival detector, PS::99a655be) is `BLOCKED / NONPHYSICAL_FLIGHT_TIME` — auxiliary, not canonical.
- **KEY FINDING**: API `/status` reports tof READY ("fs VERIFIED 50 MHz + GC-TOF::e401fecb … canonical envelope-peak TOF active") but the **canonical TOF artifact on disk was produced before fs verification and never regenerated with tof_us**. The human 5-frame check (§H) and real summary (§I) therefore cannot PASS as-is. Primary R2 remediation: rerun canonical TOF via official orchestrator with current PS + FROZEN GC, producing valid `tof_us` from `tof_samples / fs * 1e6`.

## 6. Current Target / Feature selection
- Target registry: `reference_soc_percent` = "参考SOC / Reference SOC", semantic DERIVED_REFERENCE_LABEL, source electrical XLSX retrospective — semantics correct ✔ (§O). But the existing report references `soc_reference_percent` (legacy id) — naming drift to reconcile.
- No committed workflow TARGET selection is visible (`scientific_context.target: null` in workflow-context) — TARGET step says COMPLETE while target is null: **inconsistency to fix or explain in R2**.

## 7. Preview / Dataset / Split / Models / Report (current)
- Datasets (SOC family): 4 on disk. Evaluated one: **DS::6a3142e5186fc684964ff09e** — predictors `[amplitude_a_u]` only, 3995 joined rows (features 3995 / labels 3999 → 4 rows dropped at join), leakage-safe builder v0.1.0, PS::9ebbb833, status READY_WITH_LIMITATIONS. DS::a9cf63…: 13 waveform/xcorr predictors, 3995 rows, same PS. Two SPEC_PENDING_RUN shells.
- **No dataset contains canonical TOF features** → §X answer today: current model does NOT use current canonical TOF.
- Splits: SPLIT::062cf007… — strategy LEAVE_ONE_GROUP_OUT, unit CYCLE, WITHIN_BATTERY_CROSS_CYCLE, held-out forbidden for model selection, no 3-way → leakage-safe ✔; no Random Frame Split found ✔ (§V).
- Models: 10 MODEL:: dirs under DS::6a3142e5/SPLIT::062cf007 (multiple versions per family — supersession audit needed). Comparison from artifact API: Dummy 29.61, Linear 30.86, Ridge 30.87, GB 33.78, RF 35.56 % MAE → **no model beats Dummy** ✔ honest, not a blocker.
- Report: REPORT::62c7063090dd64127175bee3 (target soc_reference_percent) with 11 machine-readable limitations — but includes `TOF_UNAVAILABLE_OR_BLOCKED` while TOF is now READY: stale semantics, must regenerate for RC (§Y).
- `/datasets` and `/splits` list endpoints return empty arrays despite artifacts on disk — list/registry wiring gap to investigate in R2.

## 8. CURRENT / STALE / LEGACY / SUPERSEDED audit (workflow-context, live)
- `artifact_freshness`: dataset=**LEGACY**, models=**STALE**, report=**STALE** — the whole downstream chain predates canonical-TOF activation. Consistent with §5/§7.
- Steps: all 8 COMPLETE, current_step=REPORT — but with a `WAITING_FOR_USER` pending action, `target:null`, and stale chain. Stepper says COMPLETE while freshness says stale: **RC1 must resolve this contradiction** (recommend: rebuild chain → all CURRENT at freeze).

## 9. Pending WAITING_FOR_USER action
- `submissions.json`: **SUB::inspectprobe0001** (source `brw018r2:inspect-probe`, save SAVED, `pending_action_resolved: false`, resume NOT_ATTEMPTED) — an inspection probe left in the real state, now driving workflow-context's RESOLVE_PENDING_ACTION. Others (SUB::0f1cda29… etc.) are BRW-018R2 visual-accept probes. Decision needed: resolve/retire probe-driven pending actions so RC demo state isn't gated by test residue.

## 10. Manual acceptance route (planned)
Overview → Resume → Target(reference_soc_percent) → Alignment → Features(canonical TOF + amplitude + SWA/BPS + validated TD/FD) → Preview(X + exactly 1 y, provenance, excluded rows) → ML-safe review (Network proof of held-out redaction) → Dataset materialize → Split → Models → Report → Assistant 10 questions → Back/Forward/DeepLink/Refresh. Checklist per 03_MANUAL_ACCEPTANCE_CHECKLIST.md with PASS/FAIL/N-A + evidence + timestamp.

## 11. Clean-room plan
Fresh output root (env redirect), official CLI/orchestrator only: raw → parse/QA → sync → MeasurementEvent → parameters → GC binding → features/TOF → target → dataset → split → models → report; compare checksums, canonical counts/IDs, TOF distributions, table schema, split membership, model metrics, report records; same-spec second run must report REUSED without refit.

## 12. Screenshot/demo plan
20 §AG screenshots from the real running stack (uvicorn 8000 + vite 5173, Playwright capture; extend existing screenshot harness pattern from BRW-025R-WF).

## 13. Release blockers & minimal remediation plan (R2)
1. **Regenerate canonical TOF** (tof_us valid, status VALID) with PS::3b512b82 + GC-TOF::e401fecb via official path — §H/I prerequisite.
2. **Rebuild CURRENT chain**: preview → dataset (demo X incl. canonical TOF + y=Reference SOC) → grouped split → fixed 5 models → report; old chain classified LEGACY/SUPERSEDED, never overwritten.
3. Resolve/retire pending test submissions (§9) so WAITING state is genuine.
4. Fix TARGET-step COMPLETE vs target:null inconsistency; align `reference_soc_percent` vs `soc_reference_percent` naming in report/manifest code.
5. Investigate empty `/datasets` `/splits` list endpoints + tof-gate-calibration GET error (wiring only, no science change).
6. Verify 4-row exclusion provenance (ambiguous events preserved, §J/R) with 20-row back-to-source spot check.
7. Then: RELEASE_MANIFEST.json, clean-room repro, 20 screenshots, runbook/thesis/freeze policy/release notes docs, full test gate, single RC1 commit, worktree clean.

Scope discipline: all items above are wiring/reproducibility/evidence/stale-state/docs — no new scientific formula, TOF method, feature family, target, split, model family, agent tool, or report semantics (per §A).
