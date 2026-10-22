# Battery Research Workbench API v1

Stable first version of the Workbench Service API (BRW-024). Shared by future UI and Agent clients; HTTP layer does validation / service invocation / serialization / error mapping only — no scientific formulas live in routes.

## Base URL

All endpoints live under `/api/v1`. OpenAPI spec: `docs/api/openapi-v1.json` (also served at `/openapi.json`).

## Resource Groups

| Group | Endpoints |
|---|---|
| system | `GET /health`, `GET /capabilities`, `GET /version`, `GET /modeling/strategies` (canonical fixed-baseline registry and configurations) |
| future readiness | `GET /experiments/{battery_id}/{experiment_id}/extension-readiness` (read-only boundary assessment); `POST /target-datasets/validate-source-evidence` (read-only manifest identity + raw checksum preflight only; does not assess target readiness or materialize); `POST .../timebase-evidence-preflight` (`timebase-evidence-preflight/1.0`; read-only raw-relative path and SHA-256/size preflight for filling source hashes); `POST/GET /experiments/{battery_id}/{experiment_id}/timebase-validations`, `GET .../timebase-validations/{validation_id}`, `POST .../timebase-validations/{validation_id}/review` (timebase-validation/1.1; evidence refs must resolve to files beneath `data/raw/`; anchor hashes are recomputed and compared; ACCEPT requires review refs and SHA-256 values distinct from proposal evidence. These checks verify file integrity/separation only, not scientific evidence adequacy or reviewer identity/independence. Acceptance requires explicit recompute and does not set `validated_sync=true`) |
| experiments | `POST /experiments` (register Battery/Experiment and operator-declared protocol/condition/time metadata), `GET /experiments`, `PATCH /experiments/{battery_id}/{experiment_id}`, `GET /experiments/{battery_id}/{experiment_id}`, `/status`, `/workspace-summary`, `/lineage`, `/results`, `/limitations`, `/evidence`, `/research-overview`, `/workflow-context` |
| runs | `POST /runs/plan`, `POST /runs/dry-run`, `POST /runs`, `GET /runs/{run_id}`, `GET /runs/{run_id}/events`, `POST /runs/{run_id}/resume`, `POST /runs/{run_id}/retry/{node_id}` |
| user-actions | `GET /runs/{run_id}/user-actions`, `POST /runs/{run_id}/user-actions/{action_id}` (typed values required; API never fills scientific values) |
| parameters | `POST /experiments/{battery_id}/{experiment_id}/parameters` (BRW-015 registry, deterministic PS::id, preserves source/verification/provenance) |
| gates | `POST /gates` (validated + deterministic), `GET /gates/{gate_id}`, `GET /experiments/{battery_id}/{experiment_id}/gates` |
| parameters | `GET /experiments/{battery_id}/{experiment_id}/parameters` |
| gates | `GET /experiments/{battery_id}/{experiment_id}/gates` |
| features | `GET /experiments/{battery_id}/{experiment_id}/features`, `GET /experiments/{battery_id}/{experiment_id}/targets` |
| datasets | `POST /datasets` (registers deterministic Dataset spec; materialize with `BUILD_DATASET` run), `GET /datasets/{dataset_id}` |
| cohorts | `POST /cohort-datasets`, `GET /cohort-datasets`, `GET /cohort-datasets/{cohort_dataset_id}` (immutable, harmonized SOC cohort); `POST /cohort-datasets/{cohort_dataset_id}/lobo-evaluations`, `GET /cohort-lobo-evaluations/{evaluation_id}` (fixed baselines, Battery-grouped LOBO) |
| splits | `POST /splits` (registers deterministic split spec only; materialize with `EVALUATION_SPLIT` run), `GET /splits/{split_id}` |
| feature-analyses | `POST /feature-analyses` (deterministic AN::id), `GET /feature-analyses/{analysis_id}` |
| models | `POST /models/baseline-runs` (selected fixed strategies — no tuning endpoint), deterministic MODEL::id |
| reports | `POST /reports` (deterministic REPORT::id), `GET /reports`, `GET /reports/{report_id}` |

Scientific reports are stored as frozen JSON/Markdown/HTML outputs with a sibling
`scientific_report_manifest.json` containing SHA-256 checksums and report identity. New
outputs are reusable only when all three files verify. Legacy reports without this sidecar
are labeled `LEGACY`; checksum, identity, or path-integrity failures are
`INTEGRITY_BLOCKED`, redacted by read APIs, and not reused by the report node.
| artifacts | `GET /artifacts/{artifact_id}`, `GET /artifacts/{artifact_id}/preview?limit≤200` (metadata only, never bulk parquet) |

Experiment identity is the composite `(battery_id, experiment_id)`.
`POST /experiments` accepts optional `start_time`, `end_time`, `protocol`, `condition_id`, and `condition_description`. These are operator-declared descriptors written to the experiment library, V1.2 `experiments.csv`, and committed intake import manifest; they do not verify protocol execution, condition truth, timezone, calibration, or synchronization. Experiment-level start/end values are never used as per-DataAsset alignment anchors. If conditions vary within one experiment, the single `condition_id` is insufficient to encode that time-varying design.

### Target definition and label evidence

`GET /experiments/{battery_id}/{experiment_id}/targets` returns target semantics,
coverage, readiness, and a `provenance` object when available. The provenance
includes target grain, independent outer unit, method ID/version, formula or
measurement-method definition, source files with source checksums, and an
explicit uncertainty state. Example:

```json
{
  "target_grain": "MEASUREMENT_EVENT",
  "independent_unit": "BATTERY",
  "method_id": "PROTOCOL_ANCHORED_SEGMENT_NORMALIZED",
  "method_version": "0.2.0",
  "definition": "soc_reference_percent_charge: 100 * Q_charged_since_empty(t) / Q_charge_segment_total",
  "source_assets": [
    {
      "asset_id": "E001",
      "source_reference": "batteries/CELL_001/EXP_001/electrical/source.xlsx",
      "sha256": "<64-character source checksum>"
    }
  ],
  "uncertainty": {
    "status": "UNKNOWN",
    "reason": "The retrospective reference-label protocol does not provide a validated uncertainty estimate."
  }
}
```

`UNKNOWN` is not zero uncertainty. A parser source checksum identifies the input
file; it is not calibration evidence. For CELL_001, Temperature remains blocked
without sensor-location/calibration validation, and SOH remains not ready with
only two independent cycle states. The generic `target-datasets` write endpoint
is not implemented. `POST /target-datasets/validate-source-evidence` only
verifies that provenance references match requested manifest-registered
DataAssets and current raw file checksums. It returns
`source_integrity=VERIFIED` but `label_source_semantics=NOT_ASSESSED` and
`target_readiness=NOT_ASSESSED`: a file match does not establish that the file
scientifically supports the declared label method. It does not resolve feature
availability, rejects paths that escape `data/raw` including symlink escapes,
and does not persist or materialize a dataset. When a matching processed parser
manifest exists, its source checksum and registered path are also checked;
conflicts return `INTEGRITY_ERROR`. Per-source `parser_provenance` is
`VERIFIED`, `NOT_AVAILABLE`, `NOT_RECORDED`, or
`CHECKSUM_VERIFIED_PATH_NOT_RECORDED`. The readiness descriptor exposes the
future versioned write contract separately. Its OpenAPI response schema is
typed and fixes `label_source_semantics`, `target_readiness`, and
`feature_availability` to `NOT_ASSESSED` and `materialization_enabled` to
`false`.

## Typical Workflow

1. `GET /api/v1/experiments/{battery_id}/{experiment_id}/workspace-summary` — readiness, limitations, next actions
2. `POST /api/v1/runs/dry-run` — what would run, what would REUSE
3. `POST /api/v1/runs` — start run (supports `Idempotency-Key` header)
4. `GET /api/v1/runs/{run_id}` — poll status
5. `GET /api/v1/runs/{run_id}/user-actions` + `POST .../user-actions/{action_id}` — resolve scientific actions (API never auto-confirms)
6. `GET /api/v1/experiments/{battery_id}/{experiment_id}/features`
7. `POST /api/v1/runs/dry-run` and `POST /api/v1/runs` with profile `BUILD_DATASET` — materialize the selected Dataset
8. `POST /api/v1/runs/dry-run` and `POST /api/v1/runs` with profile `EVALUATION_SPLIT` — materialize grouped Cycle split; this profile runs `DATASET → SPLIT`
9. `GET /api/v1/experiments/{battery_id}/{experiment_id}/results`
10. `GET /api/v1/experiments/{battery_id}/{experiment_id}/evidence` + `/limitations` + `/lineage`

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
The LOBO report's primary metrics are equal-weight macro means of held-out group metrics;
pooled-row metrics are diagnostic only. The current API labels results as declared-group
technical evaluation: `declared_group_results`, `declared_group_count`, and matching
coverage fields must not be interpreted as independently verified Battery counts. The
top-level `battery_count` and `uncertainty_assessment.independent_group_count` remain null
until physical Battery identity has been independently reviewed. Synthetic fixtures
exercise this route but do not activate real cross-battery readiness.

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
`artifact_freshness` (`CURRENT/STALE/LEGACY/SUPERSEDED/MISSING` — includes Feature Analysis
output/input checksum and identity validation; old analyses without checksums are `LEGACY`,
changed inputs are `STALE`, and damaged outputs are `INTEGRITY_BLOCKED`; a dataset without
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

## Feature–State Correlations

`GET /experiments/{battery_id}/{experiment_id}/feature-correlations` returns a typed
`FeatureCorrelationsEnvelope`; its OpenAPI response fixes the alignment guard fields.
`data.alignment_assessment` reports `VALIDATED`, `PROVISIONAL`, or `UNKNOWN`, the
`validated_sync` value, `association_scope=EXPLORATORY_ONLY`, and
`confirmatory_inference_allowed=false`. Provisional alignment does not suppress an
exploratory coefficient, but the response explicitly says that electrical-label
associations cannot support confirmatory claims until the absolute timebase is validated.

The query parameter `limit` bounds only the number of event points returned by the
diagnostic scatter plot (deterministically sampled and Battery-stratified). All joined
events in the current experiment are used for the reported correlation statistics;
the response reports both `analyzed_event_rows` and `diagnostic_points_returned` in
`meta.analysis_scope`. Do not interpret this display limit as a statistical sample cap.

Each correlation result declares `n_input_unit`, `n_valid_unit`,
`missing_count_unit`, and `excluded_ineligible_unit`. For SOC/temperature,
`n_valid` counts complete event-level feature×state pairs. For SOH, it counts
Battery/Experiment/Cycle groups after within-cycle median aggregation, while
`n_input` and missing/excluded counts remain event-row counts; consumers must
not interpret those differently-grained counts as one ratio.

Temperature correlations report the observed range and the 2 °C minimum-variation
screen in `limitations`. Meeting this operational screen is not sensor calibration
evidence, does not establish independent thermal states, and does not by itself
make Temperature a ready modeling target.

`soc_cycle_decomposition` reports descriptive within-cycle and between-cycle directions,
complete Battery/Experiment/Cycle group count, event denominator, missingness, and
sync-exclusion counts. Between-cycle coefficients are `null` when fewer than 3 complete
cycle groups are available; cycle groups are nested within Battery and are not independent
batteries. The Cycle decomposition itself provides no p-values or confidence intervals;
per-SOC-result exploratory uncertainty is reported separately (see below), and confounder
adjustment remains unavailable until an analysis plan is approved.

Each SOC correlation result now also carries exploratory uncertainty fields: `ci_low`,
`ci_high`, `interval_method` (currently `FISHER_Z`, the deterministic Fisher z transform),
`p_value_raw`, `p_value_adjusted`, `multiplicity_correction` (currently `BENJAMINI_HOCHBERG`
over the declared method × scope family only), `replication_factor`
(`n_valid / independent_group_count`), and `pseudo_replication_status`. A
`replication_factor` greater than 1 means the event rows are repeated measures of the same
independent unit and must not be read as additional independent evidence. All of these
fields are optional and default to `null`; the point `coefficient` is never recomputed or
adjusted. `data.uncertainty_summary` reports the family label, family size, and how many
intervals were estimable. `data.inference_assessment.confidence_interval`,
`p_value`, and `multiple_comparison` reflect this read-out, while
`confirmatory_inference_enabled` stays `false`: an exploratorily estimated interval is not
a pre-registered confirmatory analysis.

The legacy property `soc_by_battery_condition` remains sliced by Battery and the electrochemical
phase (`overall`, `charge`, `discharge`, `rest`); it does not represent experiment
`condition_id`. A separate `data.declared_condition_analysis` reads the optional
`data/annotations/{battery_id}/{experiment_id}/condition_segments.csv` declaration and returns `NOT_CONFIGURED`,
`NO_SEGMENTS`, or `AVAILABLE`, plus event-assignment status counts and descriptive
Pearson/Spearman Reference-SOC results. Assignment is allowed only when a canonical event
and segment reference the same ultrasound DataAsset clock; cross-asset clock transfer is
blocked. Results retain `declaration_status=OPERATOR_DECLARED` and
`absolute_timebase_status=synchronization_status=NOT_ASSESSED`; they are live exploratory
results only, not frozen report artifacts or model inputs. This field does not turn an
operator declaration into verified condition truth, and it provides no confidence intervals,
p-values, multiplicity correction, or confounder adjustment. CELL_001 currently has no
condition-segment manifest, so it reports `NOT_CONFIGURED`.

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
# Analysis plan status

`GET /api/v1/experiments/{battery_id}/{experiment_id}/analysis-plan-status` is a read-only
lookup of `data/annotations/studies/{study_id}/analysis-plan.yaml`. A plan is associated
with an experiment only when it explicitly declares the exact Battery/Experiment pair.
The endpoint reports missing, incomplete, invalid, or ambiguous registrations and never
enables confirmatory inference or certifies scientific/data readiness. Correlation and
feature-ranking responses expose the same registration status under
`inference_assessment.analysis_plan`.
