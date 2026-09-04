# Battery Research Workbench API v1

Stable first version of the Workbench Service API (BRW-024). Shared by future UI and Agent clients; HTTP layer does validation / service invocation / serialization / error mapping only — no scientific formulas live in routes.

## Base URL

All endpoints live under `/api/v1`. OpenAPI spec: `docs/api/openapi-v1.json` (also served at `/openapi.json`).

## Resource Groups

| Group | Endpoints |
|---|---|
| system | `GET /health`, `GET /capabilities`, `GET /version` |
| experiments | `GET /experiments`, `GET /experiments/{battery_id}/{experiment_id}`, `/status`, `/workspace-summary`, `/lineage`, `/results`, `/limitations`, `/evidence` |
| runs | `POST /runs/plan`, `POST /runs/dry-run`, `POST /runs`, `GET /runs/{run_id}`, `GET /runs/{run_id}/events`, `POST /runs/{run_id}/resume`, `POST /runs/{run_id}/retry/{node_id}` |
| user-actions | `GET /runs/{run_id}/user-actions`, `POST /runs/{run_id}/user-actions/{action_id}` (typed values required; API never fills scientific values) |
| parameters | `POST /experiments/{battery_id}/{experiment_id}/parameters` (BRW-015 registry, deterministic PS::id, preserves source/verification/provenance) |
| gates | `POST /gates` (validated + deterministic), `GET /gates/{gate_id}`, `GET /experiments/{battery_id}/{experiment_id}/gates` |
| parameters | `GET /experiments/{battery_id}/{experiment_id}/parameters` |
| gates | `GET /experiments/{battery_id}/{experiment_id}/gates` |
| features | `GET /experiments/{battery_id}/{experiment_id}/features` |
| datasets | `POST /datasets` (deterministic, idempotent REUSED), `GET /datasets/{dataset_id}` |
| splits | `POST /splits` (deterministic, idempotent REUSED), `GET /splits/{split_id}` |
| feature-analyses | `POST /feature-analyses` (deterministic AN::id), `GET /feature-analyses/{analysis_id}` |
| models | `POST /models/baseline-runs` (fixed baseline only — no tuning endpoint), deterministic MODEL::id |
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

## UserActionRequired

Pending actions are exposed via `GET /runs/{run_id}/user-actions` with typed kinds
(`MISSING_SAMPLING_RATE`, `SELECT_GATE`, `CONFIRM_FEATURE_SELECTION`, `SELECT_SPLIT_SCHEME`).
The API never fills scientific values on the user's behalf; resolution requires an explicit
`POST` with `values`. After submit, `POST /runs/{run_id}/resume` continues the run.

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
