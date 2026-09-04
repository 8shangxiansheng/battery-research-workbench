# BRW-024 WORKBENCH SERVICE API HARDENING REPORT

## Status

`BRW-024 COMPLETE`

## Architecture

```text
FastAPI /api/v1
→ WorkbenchService
→ ScientificRunService + BRW-023 reporting/registry services
→ PipelineOrchestrator + domain services
→ scientific core / persistence
```

HTTP routes only validate, invoke, serialize, and map errors. No route reads Parquet/Zarr,
computes SOC/TOF/features/metrics, fits a model, or duplicates DAG logic.

## API Version and endpoints

Stable base is `/api/v1`. Endpoint groups cover system, experiments, artifacts, runs,
user-actions, parameters, gates, features, feature analysis, datasets, splits, fixed baseline
models, reports, evidence, and lineage. Experiment identity is always
`battery_id + experiment_id`.

## WorkbenchService and contracts

- Public Pydantic DTOs reject unknown fields, invalid IDs, traversal, and oversized lists.
- Success and error envelopes carry a per-request `request_id`.
- Public payloads remove filesystem paths and internal orchestrator representations.
- Existing artifact lookup reads bounded manifest metadata; it never bulk-serializes Parquet or
  waveform arrays.
- Deterministic resource specs persist under the run service root and survive service restart.
- Parameter writes call the BRW-015 registry and preserve source, verification, and provenance.
- Report creation calls the BRW-023 aggregation-only reporting node.

## Status and errors

Canonical errors are `VALIDATION_ERROR`, `NOT_FOUND`, `CONFLICT`,
`ARTIFACT_NOT_AVAILABLE`, `SCIENTIFIC_ACTION_REQUIRED`,
`SCIENTIFIC_READINESS_BLOCKED`, `INTEGRITY_ERROR`, `UNSUPPORTED_OPERATION`, and
`INTERNAL_ERROR`. Unexpected exceptions hide traceback, secrets, and local paths.

Unavailable scientific values use `null + status + reason`. The API preserves
`validated_sync=false`, `PROVISIONAL`, `RETROSPECTIVE_SOC_REFERENCE`, SOH `NOT_READY`, TOF
`BLOCKED`, limited cross-cycle evaluation, EvidenceType, and Limitation severity.

## User actions

Run actions can be listed, submitted, resumed, and retried through the BRW-019 facade. Typed
validation covers `MISSING_SAMPLING_RATE`, `SELECT_GATE`, `CONFIRM_FEATURE_SELECTION`, and
`SELECT_SPLIT_SCHEME`; the API never fills or confirms scientific values automatically.

## Idempotency, pagination, and preview

- Gate, feature analysis, dataset, split, model, and report requests use semantic IDs and return
  `REUSED` for the same scientific request.
- Run creation supports `Idempotency-Key`; same key/different payload returns `409`.
- Experiments, runs, results, and reports use stable `limit + cursor` pagination.
- Preview is capped at 200 rows and waveform bulk JSON is not exposed.

## Evidence, limitations, and lineage

Evidence types and source artifact IDs pass through unchanged; availability is derived from
manifest existence on disk. Lineage is built from canonical manifest IDs only and removes all
filesystem fields.

## OpenAPI and documentation

- Snapshot: `docs/api/openapi-v1.json`
- Usage and workflow: `docs/api/README.md`
- Generator: `scripts/generate_openapi.py`
- Snapshot, tags, typed error schemas, `/api/v1`, endpoint inventory, and breaking-change checks
  are covered by tests.

## Security

The API rejects path traversal and invalid identifiers, forbids arbitrary request fields/paths,
bounds feature/gate/preview payloads, does not execute arbitrary Python, excludes secrets and
tracebacks from responses, and records structured request metadata without raw waveform content.

## Demo

The current CELL_001 / EXP_001 workspace is reported as
`READY_FOR_LIMITED_EVALUATION` because dataset/split/model artifacts are available. TOF remains
`BLOCKED`, SOH remains `NOT_READY`, sync remains provisional, and pending feature-selection user
actions remain visible. No unavailable result is represented as zero.

## Scientific invariants and input integrity

- No scientific formula or model fit was added to the API layer.
- GET endpoints do not start/resume runs, materialize artifacts, or refit models.
- Reports aggregate existing artifacts only.
- `git status --short data/raw data/processed data/artifacts` is empty.
- BRW-003–023 raw and scientific output artifacts were not modified.

## Tests and gates

- API suite: 68 passed across 5 files (contracts 24, system 14, runs 12, resources 16, openapi 2).
- Full suite: 851 collected, 849 passed, 2 skipped.
- `ruff check .`: passed.
- `ruff format --check`: passed (API + tests + full repo).
- API mypy scope with runtime Python 3.13: passed, 11 source files.
- `git diff --check`: passed.

The repository-wide default mypy command still conflicts with the existing
`python_version = 3.11` setting when executed in the project Python 3.13 environment because the
installed NumPy stubs contain Python 3.12+ syntax. The BRW-024 supported scope passes when mypy is
run with the actual Python 3.13 target.

## Final questions

- Can UI use API without reading parquet/manifests directly? **YES**
- Can future Agent use same service boundary? **YES**
- Are scientific algorithms kept out of routes? **YES**
- Are blocked/waiting states represented without HTTP 500? **YES**
- Can UserActionRequired be resolved through API? **YES**
- Are deterministic scientific creates idempotent? **YES**
- Can evidence semantics pass unchanged? **YES**
- Can clients inspect lineage/limitations/results? **YES**
- Do read-only endpoints avoid recomputation? **YES**
- Is OpenAPI v1 stable/test-covered? **YES**
- Are path traversal and secret leaks guarded? **YES**
- Are BRW-003–023 scientific artifacts unchanged? **YES**

All core convergence questions are YES. Stop before BRW-025 UI and BRW-026 Agent work.
