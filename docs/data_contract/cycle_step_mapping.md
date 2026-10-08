# Cycle/Step Mapping Declaration — V1.0

This optional companion CSV records a human-reviewed mapping from source-local
Electrical `(DataAsset, cycle_index_raw, step_index_raw)` identities to
experiment-level canonical Cycle/Step indices.

File: `data/annotations/{battery_id}/{experiment_id}/cycle-step-mapping.csv`.
Use the [blank template](../templates/cycle-step-mapping.csv). It is separate
from immutable `data/raw/` and does not modify parser outputs.

## Contract

Each row maps one source Cycle/Step pair to one canonical pair. The file must
cover every source pair in the current `cycles.parquet` and `steps.parquet`
exactly once. A source Cycle must map consistently to one canonical Cycle;
distinct source steps may be placed in the same canonical Cycle to declare a
cross-asset continuation, but V1.0 rejects many-to-one mappings onto the same
canonical Cycle/Step. Canonical indices are operator declarations, not values
inferred from file order or raw numbering.

Every row pins the Electrical parser manifest SHA-256 and a raw-relative
evidence file SHA-256. Review status must be `ACCEPTED`, reviewer/rationale must
be present, and `reviewed_at` must be ISO-8601 with an explicit UTC offset.
This records an unauthenticated operator attestation; checksum validation does
not authenticate the reviewer or prove that two source segments belong to one
physical Cycle.

## Current implementation boundary

`python -m battery_workbench.provenance.cycle_step_mapping <csv> --battery-id
<id> --experiment-id <id> --raw-root data/raw --processed-root data/processed`
checks identity completeness, current Electrical parser outputs, parser
manifest binding, raw evidence bytes, review metadata and one-to-one mapping
structure. The `project_canonical_cycle_step` API can then add canonical keys
to an in-memory step-level table while preserving `cycle_index_raw`,
`step_index_raw`, DataAsset identity and source locators. Each projected row
also carries the mapping ID/checksum, pinned parser-manifest checksum,
row-specific evidence checksum, and unauthenticated review status. A
successful preflight reports
`CYCLE_STEP_MAPPING_CONTRACT_VALIDATED`; it explicitly reports
`mapping_application_status=PROJECTION_AVAILABLE_NOT_INTEGRATED`,
`label_generation_authorized=false`, and scientific continuity
`NOT_ASSESSED`.

The projection is deliberately not wired into Reference Label generation, SOH
aggregation, Dataset construction, or modeling, so those consumers continue to
fail closed on ambiguous multi-asset source Cycle identities. A later stage
must wire the reviewed mapping into each relevant scientific join and add
multi-XLSX golden validation. Never edit processed Parquet to mimic a mapping.
