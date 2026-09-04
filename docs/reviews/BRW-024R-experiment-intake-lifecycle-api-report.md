# BRW-024R EXPERIMENT INTAKE & LIFECYCLE API REPORT

## Reference Repository Review

| Repository/Product | Observed Pattern | Why It Works | Our Adaptation | Direct Reuse/Adapt/Reject | License/Integration Note |
|---|---|---|---|---|---|
| FiftyOne | Named dataset importers; managed media dir; DatasetInfo import provenance | Detection decoupled from parsing; staged media keeps source immutable; provenance written once | intake_session ≈ import step; staging dir; adapter_id+version → DataAsset manifest | Adapt (concept only) | AGPL/commercial — zero code copied |
| MLflow | GET /experiments list+filter+pagination; lifecycle_stage active/deleted; bounded artifact REST; archive state | Server-driven library; two-state lifecycle; artifacts never expose filesystem paths | Experiment Library list/filter/limit/cursor; ARCHIVED stage; artifact metadata-only endpoint; latest_run = run_id only | Adapt (REST shape) | Apache-2.0 |
| Kedro-Viz | Pipeline↔dataset dual view; dataset card (layer/type/checksum); node lineage from manifest | Explicit stage↔asset linkage; lineage derived, not indexed | commit → recommended_next_action=RUN_INGEST_TO_MEASUREMENT_EVENTS bridges to BRW-019; DataAsset registry = dataset card | Adapt (navigation semantics) | Apache-2.0 |

## Current Gap (before this round)

- No POST /experiments (experiments only existed as demo CSV); no lifecycle status.
- No intake session / staging / detect / validate / commit.
- BRW-007 registry had no content-sniffing path (added at intake layer reusing the same registry).
- 2 latent pipeline bugs surfaced only by a truly fresh experiment (fixed additively, see below).

## Experiment Lifecycle

DRAFT → AWAITING_DATA → IMPORTING → IMPORT_VALIDATION_REQUIRED → READY_FOR_PIPELINE
(→ BRW-019 runs: WAITING_FOR_USER / RUNNING / READY / FAILED) → ARCHIVED.
Scientific readiness (TOF BLOCKED, SOH NOT_READY) tracked separately — never "experiment failed".

## Experiment Library

POST /api/v1/experiments (explicit battery/experiment id or deterministic EXP_%03d policy);
GET list with status/battery_id/is_demo filters + limit/cursor; GET/PATCH single; POST archive.
Legacy demo experiments (CELL_001/EXP_001) remain visible, merged into the list.

## Intake Sessions

POST /experiments/{id}/intake-sessions; GET /intake-sessions/{id}.
States: DRAFT → ASSETS_RECEIVED → DETECTED → VALIDATED → COMMITTED (+FAILED/CANCELLED/EXPIRED).
recommended_next_action guides each step.

## Upload/Staging

Multipart upload → staging/intake/{session_id}/ with server-generated stored filename
(original filename = metadata only). sha256+size+received_at per asset. Limits: 100 MB/asset,
20 assets/session. Path traversal rejected (SAFE_FILENAME + resolve containment).

## Adapter Detection

Reuses BRW-007 DataAdapterRegistry (ElectricalAdapter/UltrasoundAdapter) — no route sniffing.
States: DETECTED_UNIQUE / DETECTED_AMBIGUOUS / UNSUPPORTED, with adapter_id, adapter_version,
asset_role, detection_reason, matched_signatures. Ambiguous/unsupported stop with typed errors
AMBIGUOUS_ADAPTER (409) / UNSUPPORTED_FILE_FORMAT (409); never silently select.

## Validation

Three dimensions reported separately: FORMAT_VALIDITY (real parser structure check),
SCIENTIFIC_METADATA_COMPLETENESS, PIPELINE_READINESS (ELECTRICAL+ULTRASOUND roles).
sampling_rate_hz stays null + UNKNOWN; validation detail states "10s frame cadence is NOT a
waveform fs". Metadata-incomplete (unknown fs) is still a VALID intake (T29).

## Commit

POST /intake-sessions/{id}/commit: staged → canonical raw/batteries/{b}/{e}/{role_dir}/,
manifest rows appended (data_assets.csv with sha256/role/original_filename/intake_session_id/
adapter_id/adapter_version + experiments.csv with battery_id), import manifest persisted with
checksum. Repeated commit → idempotent REUSED (same import_manifest_checksum). Checksum conflict
with committed raw → INTEGRITY_ERROR 409 + preserved staging (rollback/recovery). Raw immutable.

## Asset Registry / Provenance

Committed DataAsset rows carry asset_id, experiment_id, modality, relative_path, sha256,
role, original_filename, adapter_id, adapter_version, source_type=INTAKE_STAGING,
intake_session_id. GET /experiments/{id}/assets lists them.

## User Actions

Framework unchanged from BRW-019; intake adds typed needs SELECT_ADAPTER (ambiguous),
CONFIRM_ASSET_ROLE, PROVIDE_REQUIRED_METADATA (fs for later TOF stage), RESOLVE_DUPLICATE.
Unknown fs does not block intake commit; TOF stages may still WAITING_FOR_USER later.

## API Endpoints (additive; 51 → 66 total paths)

GET /api/v1/intake/capabilities · POST/GET /api/v1/experiments · GET/PATCH /api/v1/experiments/{b}/{e} ·
POST archive · POST intake-sessions · GET intake-sessions/{sid} · POST assets · GET assets ·
GET assets/{id}/preview (bounded: sheets+row counts / frame count+samples/frame+elapsed range;
no full file) · POST detect/validate/commit/cancel · GET experiments/{id}/assets ·
GET experiments/{id}/intake-history · GET experiments/{id}/lifecycle-events.
New error codes additive: UNSUPPORTED_FILE_FORMAT, AMBIGUOUS_ADAPTER, DUPLICATE_ASSET,
INTAKE_NOT_VALIDATED, INTAKE_ALREADY_COMMITTED, UPLOAD_TOO_LARGE, ASSET_ROLE_CONFLICT.

## Security

No client filesystem paths; SAFE_FILENAME + resolved-path containment in staging; upload size/asset
limits; empty/unsafe filename rejected; no secrets or absolute paths in error bodies; extension/MIME
is a hint only — registry detection decides; content-over-extension verified by T22.

## New Experiment E2E (§41)

tests/unit/test_intake_e2e.py: create CELL_100/EXP_100 via POST /experiments → intake session →
multipart upload (xlsx+txt) → detect (BRW-007, both DETECTED_UNIQUE) → validate (pass, fs UNKNOWN) →
commit (canonical raw + manifests) → POST /runs INGEST_TO_MEASUREMENT_EVENTS → real
MEASUREMENT_EVENTS parquet materialized under multimodal/CELL_100/EXP_100. No manual file placement.

## Existing Demo Regression

CELL_001/EXP_001 flow unchanged: full backend suite 900 passed / 2 skipped (was 855+2 before;
+45 intake tests). Legacy demo experiments still listed/summarized (backward-compatible route
delegation). data/raw + data/processed: 0 git changes.

## Latent Pipeline Bugs Fixed (additive, found by fresh-experiment flow)

1. orchestrator nodes.py: producer_version read from manifest.parser_version attribute that never
   existed on ElectricalOutputManifest/UltrasoundOutputManifest dataclasses → now read from the
   written parser_manifest.json (JSON is authoritative).
2. ULTRASOUND_TIMESTAMPS node passed exp_dir as output_dir to write_timestamp_state, which appends
   its own synchronization/{b}/{e} → doubled nesting broke downstream lookups → pass processed_root.
3. TIME_ANCHOR config path assumed raw_root.parent.parent/configs; sandbox raw roots have none →
   fallback to repo-shipped configs/time_anchor.yaml.

## Input Integrity

git status data/raw data/processed → empty. All sandbox tests use tmp roots. Frontend untouched
behavior: 31 passed + E2E; OpenAPI regenerated additively; BRW-025 drift test green.

## Tests

- tests/unit/test_intake_lifecycle.py: 44 passed (T01–T55 behavioral coverage: create/ID policy/
  duplicate/demo flag/list+filter+pagination; session create/status/cancel/immutable/expired;
  upload safe-name/sha256/size/multi/checksums; detection electrical/ultrasound/unsupported/
  ambiguous/provenance; validation structure/unknown-fs/cadence-not-fs/missing-role/metadata≠format;
  commit validated/idempotent/blocked/rollback/registry/provenance/immutable; security traversal/
  arbitrary-path/oversize/leak; isolation multi-experiment/locators)
- tests/unit/test_intake_e2e.py: 1 passed (sandbox full pipeline)
- Backend total: 900 passed / 2 skipped; ruff + format + mypy (intake+api) clean; git diff --check clean

## Final Answers (§44)

1. Can a user create a brand-new experiment through public API? **YES**
2. Can electrical/ultrasound data be imported without manual canonical filesystem placement? **YES**
3. Does intake use BRW-007 Adapter Registry? **YES**
4. Can unsupported/ambiguous formats stop for user confirmation? **YES**
5. Are unknown scientific metadata preserved? **YES** (fs null+UNKNOWN)
6. Is 10s cadence prevented from becoming waveform fs? **YES** (asserted in validation detail + tests)
7. Are committed raw assets immutable/checksummed? **YES**
8. Can a second experiment reuse the same workflow? **YES** (E2E proves it)
9. Is CELL_001/EXP_001 only a demo? **YES** (is_demo flag; API-created experiments independent)
10. Can BRW-025R build Experiment Library + Import Wizard on this API? **YES** (all endpoints typed + OpenAPI)
