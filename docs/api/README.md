# Battery Research Workbench API v1

Stable first version of the Workbench Service API (BRW-024). Shared by future UI and Agent clients; HTTP layer does validation / service invocation / serialization / error mapping only — no scientific formulas live in routes.

## Base URL

All endpoints live under `/api/v1`. OpenAPI spec: `docs/api/openapi-v1.json` (also served at `/openapi.json`).

## Resource Groups

| Group | Endpoints |
|---|---|
| system | `GET /health`, `GET /capabilities`, `GET /version`, `GET /modeling/strategies` (canonical fixed-baseline registry and configurations) |
| future readiness | `GET /experiments/{battery_id}/{experiment_id}/extension-readiness` (read-only boundary assessment; cohort API is implemented, while timebase validation, generic target-dataset, and tuning write paths remain unavailable) |
| experiments | `GET /experiments`, `GET /experiments/{battery_id}/{experiment_id}`, `/status`, `/workspace-summary`, `/lineage`, `/results`, `/limitations`, `/evidence`, `/research-overview`, `/workflow-context` |
| runs | `POST /runs/plan`, `POST /runs/dry-run`, `POST /runs`, `GET /runs/{run_id}`, `GET /runs/{run_id}/events`, `POST /runs/{run_id}/resume`, `POST /runs/{run_id}/retry/{node_id}` |
| user-actions | `GET /runs/{run_id}/user-actions`, `POST /runs/{run_id}/user-actions/{action_id}` (typed values required; API never fills scientific values) |
| parameters | `POST /experiments/{battery_id}/{experiment_id}/parameters` (BRW-015 registry, deterministic PS::id, preserves source/verification/provenance) |
| gates | `POST /gates` (validated + deterministic), `GET /gates/{gate_id}`, `GET /experiments/{battery_id}/{experiment_id}/gates` |
| parameters | `GET /experiments/{battery_id}/{experiment_id}/parameters` |
| gates | `GET /experiments/{battery_id}/{experiment_id}/gates` |
| features | `GET /experiments/{battery_id}/{experiment_id}/features` |
| datasets | `POST /datasets` (deterministic, idempotent REUSED), `GET /datasets/{dataset_id}` |
| cohorts | `POST /cohort-datasets`, `GET /cohort-datasets`, `GET /cohort-datasets/{cohort_dataset_id}` (immutable, harmonized SOC cohort); `POST /cohort-datasets/{cohort_dataset_id}/lobo-evaluations`, `GET /cohort-lobo-evaluations/{evaluation_id}` (fixed baselines, Battery-grouped LOBO) |
| Cycle/Step mapping | `GET /experiments/{battery_id}/{experiment_id}/cycle-step-mapping` (current sidecar checksum/status, read-only); `GET .../cycle-step-mapping/source-inventory` (verified parser source pairs, no canonical assignments); `GET .../cycle-step-mapping/draft` (unreviewed CSV inventory with parser-derived source IDs/checksums; canonical assignments blank); `POST .../cycle-step-mapping/preflight` (validates operator-supplied CSV, read-only); `PUT .../cycle-step-mapping` (explicitly confirmed, revalidated, content-addressed revision outside immutable raw; optimistic checksum prevents stale overwrite); `GET .../cycle-step-mapping/revisions` and `GET .../revisions/{sha256}` (integrity-checked revision metadata and CSV download, read-only) |
| splits | `POST /splits` (deterministic, idempotent REUSED), `GET /splits/{split_id}` |
| feature-analyses | `POST /feature-analyses` (deterministic AN::id), `GET /feature-analyses/{analysis_id}` |
| models | `POST /models/baseline-runs` (selected fixed strategies — no tuning endpoint), deterministic MODEL::id |
| reports | `POST /reports` (deterministic REPORT::id), `GET /reports`, `GET /reports/{report_id}` |
| artifacts | `GET /artifacts/{artifact_id}`, `GET /artifacts/{artifact_id}/preview?limit≤200` (metadata only, never bulk parquet) |

Experiment identity is the composite `(battery_id, experiment_id)`.

## Typical Workflow

1. `GET /api/v1/experiments/{battery_id}/{experiment_id}/workspace-summary` — readiness, limitations, next actions
2. `POST /api/v1/runs/dry-run` — what would run, what would REUSE
3. `POST /api/v1/runs` — start run (supports `Idempotency-Key` header)
4. `GET /api/v1/runs/{run_id}` — poll status
5. `GET /api/v1/runs/{run_id}/user-actions` + `POST .../user-actions/{action_id}` — resolve scientific actions (API never auto-confirms)
6. `GET /api/v1/experiments/{battery_id}/{experiment_id}/features`
7. `POST /api/v1/datasets`, `POST /api/v1/splits` — deterministic create, REUSED if canonical artifact exists
8. `GET /api/v1/experiments/{battery_id}/{experiment_id}/results`
9. `GET /api/v1/experiments/{battery_id}/{experiment_id}/evidence` + `/limitations` + `/lineage`

## Response Envelope

Success:

```json
{"data": {...}, "meta": {}}
```

Error:

```json
{"error": {"code": "NOT_FOUND", "message": "...", "details": {}, "request_id": "..."}}
```

## Status / Error Taxonomy

| Code | HTTP | Meaning |
|---|---|---|
| VALIDATION_ERROR | 400 | malformed input, invalid ID |
| NOT_FOUND | 404 | resource does not exist |
| CONFLICT | 409 | idempotency-key payload mismatch |
| ARTIFACT_NOT_AVAILABLE | 404 | semantic artifact missing |
| SCIENTIFIC_ACTION_REQUIRED | 409 | user action needed (e.g. MISSING_SAMPLING_RATE) — not a server fault |
| SCIENTIFIC_READINESS_BLOCKED | 409 | SOH NOT_READY, TOF BLOCKED — not a server fault |
| INTEGRITY_ERROR | 409 | artifact integrity mismatch |
| UNSUPPORTED_OPERATION | 400 | e.g. tuning endpoint (does not exist by design) |
| INTERNAL_ERROR | 500 | unexpected bug; traceback logged server-side only, client gets `request_id` |

Scientific blocked/waiting states are **409 with typed error**, never HTTP 500.

### Cohort / battery-level evaluation

Cohort inputs reference server-side source dataset IDs, not client paths. V1 accepts only
manifest-backed retrospective reference-SOC datasets with identical SOC formula/temporality
and exact, definition-backed feature units/versions. Unit conversion is not implemented.
Source manifest/data/feature-definition checksums make a cohort stale if its inputs change.
The LOBO report's primary metrics are equal-weight macro means of held-out battery metrics;
pooled-row metrics are diagnostic only. Synthetic fixtures exercise this route but do not
activate real cross-battery readiness.

## UserActionRequired

Pending actions are exposed via `GET /runs/{run_id}/user-actions` with typed kinds
(`MISSING_SAMPLING_RATE`, `SELECT_GATE`, `CONFIRM_FEATURE_SELECTION`, `SELECT_SPLIT_SCHEME`).
The API never fills scientific values on the user's behalf; resolution requires an explicit
`POST` with `values`. After submit, `POST /runs/{run_id}/resume` continues the run.

## Workflow Context (BRW-025R-WF)

`GET /experiments/{battery_id}/{experiment_id}/workflow-context` is the canonical read model every page
(Overview / Target / Alignment / Features / Preview / Dataset / Split / Models / Report / Assistant)
must consume — no page re-derives step status or next action on its own.

It returns `current_step`, per-step `step_statuses`
(`COMPLETE/CURRENT/READY/BLOCKED/STALE/NOT_STARTED/LIMITED`) over the fixed order
`TARGET → ALIGNMENT → FEATURES → PREVIEW → DATASET → SPLIT → MODELS → REPORT`, committed
scientific identity per step (draft/SPEC_PENDING_RUN manifests are reported as drafts, never
committed), structured `blocking` (`blocking_code/blocking_message/required_action/scientific_reason`),
`artifact_freshness` (`CURRENT/STALE/LEGACY/SUPERSEDED/MISSING` — e.g. a dataset without
`tof_method_id` is LEGACY and marks downstream models/report STALE), `pending_action`
(BRW-018R2 WAITING_FOR_USER submissions, same-run resume), `assistant_context` (session phase /
pending / next actions) and the single `recommended_next_action` with typed `action_id` + route.

Read-only and zero-recomputation by contract: it only aggregates existing artifacts and manifests;
it never computes TOF/CE/correlation/model metrics/split and never writes scientific artifacts.

## Evidence Semantics

Evidence entries pass through BRW-023 unchanged: `evidence_type` (7-level enum:
`DIRECT_CURRENT_ARTIFACT`, `PRIOR_AUDIT`, `SOURCE_INFERENCE`, `DERIVED_COMPUTATION`,
`USER_PROVIDED_CONTEXT`, `BLOCKED`, `UNAVAILABLE`), `evidence_ref`, and source artifact
IDs are never promoted by the API layer. Unavailable values are `null` + `status`/`reason`
(e.g. TOF: `value=null`, `status=BLOCKED`), never `0`.

## Idempotency

- Deterministic scientific creates (`POST /datasets`, `POST /splits`, `POST /reports`):
  same semantic spec → same semantic ID, `status=REUSED`.
- Run creation: optional `Idempotency-Key` header. Same key + same payload → same
  `run_id` returned; same key + different payload → `409 CONFLICT`.

## Pagination

List endpoints (`experiments`, `results`) accept `limit` (1–500) and `cursor`
(deterministic ordering by ID). `meta.next_cursor` is set when more pages exist.

## Security Baseline

- No path traversal: resource IDs validated against `^[A-Za-z0-9_.:@-]+$`; `..` rejected
- No arbitrary filesystem access from clients
- Bounded payload sizes (feature lists, previews: limit ≤ 500)
- No secrets or tracebacks in error responses; `request_id` for correlation
- Read-only GET endpoints never materialize artifacts or refit models

## Client Contract

Clients depend on `artifact_id` / semantic IDs and availability status — never on
filesystem paths. Filesystem locations appear only in debug/admin metadata as opaque
`path_hint` when present.
