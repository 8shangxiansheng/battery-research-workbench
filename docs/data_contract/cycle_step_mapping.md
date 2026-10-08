# Cycle/Step Mapping Declaration — V1.0

This optional companion CSV records a human-reviewed mapping from source-local
Electrical `(DataAsset, cycle_index_raw, step_index_raw)` identities to
experiment-level canonical Cycle/Step indices.

File: `data/annotations/{battery_id}/{experiment_id}/cycle-step-mapping.csv`.
Use the [blank template](../../frontend/public/cycle-step-mapping.csv). It is separate
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
structure. The preflight itself is not authorization to generate labels. The
`project_canonical_cycle_step` and `project_canonical_cycles` APIs can add
canonical keys to in-memory tables while preserving source-local indices,
DataAsset identity and source locators. Projected rows carry the mapping
ID/checksum, pinned parser-manifest checksum, evidence checksum, and
unauthenticated review status. The deterministic Label Builder independently
revalidates the mapping when it is explicitly passed; the workflow node
discovers `data/annotations/{battery_id}/{experiment_id}/cycle-step-mapping.csv`
when present. A successful preflight reports
`CYCLE_STEP_MAPPING_CONTRACT_VALIDATED`; this means only that the declaration
and its evidence are structurally/currently valid. It separately reports
`mapping_application_status` as either
`LABEL_BUILDER_CONSUMER_AVAILABLE` or
`LABEL_BUILDER_CONSUMER_UNAVAILABLE`, plus
`mapping_application_reason` when unavailable. A structurally valid mapping
that assigns multiple source Cycles to one canonical Cycle is currently not
consumable by the Reference Label builder: no cross-source capacity
aggregation contract has been established. The CSV can still be saved as an
operator-reviewed annotation, but saving does not make label generation
available. Label generation remains unauthorized by preflight, and scientific
continuity remains `NOT_ASSESSED` in either case.

The API exposes the current sidecar checksum and a separate explicit save
operation. Saving requires `confirm_reviewed=true`, the caller's expected
active checksum (null only when no active mapping exists), and fresh server
validation against current raw evidence and parser outputs. The active sidecar
is atomically replaced; each previous and new CSV is retained under
`data/annotations/{battery_id}/{experiment_id}/cycle-step-mapping.revisions/`
as `<sha256>.csv`. A stale expected checksum returns `CONFLICT`; an identical
current revision is idempotent. This is local content-addressed history, not
authenticated identity or a tamper-proof audit log. Because the API has no
authentication by default, keep the workbench bound to localhost or behind a
trusted authenticated proxy.

The read-only API lists these revisions by SHA-256 and active status and serves
the exact CSV bytes only after rechecking the digest. Historical snapshots are
for review/recovery; their presence does not mean they remain valid against the
current raw evidence or parser outputs. A digest mismatch blocks listing and
download rather than silently repairing the snapshot. Active and revision
sidecars are opened with symlink-resistant reads. POSIX readers traverse from
the data root with descriptor-relative `O_NOFOLLOW`; Windows readers check
reparse points and compare the opened file identity before and after reading.
On Windows, keep the annotations directory writable only by the service
account because Python does not expose the same portable descriptor-relative
open API there.

The read-only `GET .../cycle-step-mapping/draft` endpoint can prepare an
unreviewed inventory from current `steps.parquet` and parser provenance. It
prefills source-local asset/cycle/step identity and source/parser checksums, but
leaves canonical Cycle/Step, mapping ID, reviewer, review timestamp, status and
rationale blank. It never proposes cross-asset equivalence, and the draft must
fail preflight until a researcher completes and reviews it. The copied raw
workbook checksum is lineage evidence only; it does not prove physical cycle
continuity or substitute for an experiment record supporting the mapping.
The workbench's in-page editor consumes the same inventory, keeps all canonical
fields blank until an operator enters them, and invalidates a previous preflight
whenever a field changes. A save can only use the exact CSV bytes that passed
the latest preflight; it still requires separate confirmation and server-side
revalidation.

Each evidence path in the editor is raw-relative and can be changed to another
source record (for example, an acquisition log) only after the read-only
`POST .../cycle-step-mapping/evidence-check` resolves it below `data/raw/` and
returns its SHA-256. Symlinks that escape the raw root are rejected, and files
larger than 64 MiB are not hashed by this endpoint. This verifies path
confinement and byte identity only; a researcher remains responsible for
judging whether the referenced record supports the declared correspondence.

If API status returns `INTEGRITY_ERROR` for revision history, saving and
replacement remain blocked; the application does not rewrite or discard a
damaged snapshot. Preserve a copy of the full experiment annotation directory,
restore it from a trusted backup, then retry status inspection. If the active
mapping is merely `INVALID` because parser/raw evidence changed, prepare and
review a new CSV against current evidence, then use the normal preflight/save
flow. Do not edit processed Parquet or re-hash a damaged historical file to
make it appear valid.

For label generation, V1 currently requires exactly one complete source Cycle
per canonical Cycle. It supports distinct source assets whose raw Cycle
numbers restart, provided the reviewed mapping assigns distinct canonical
Cycle IDs. It rejects many-to-one source-cycle aggregation (for example,
combining partial Cycle rows from multiple assets) because no capacity
aggregation contract has been validated. Without a mapping, label generation
fails closed for any Experiment with multiple Electrical DataAssets, even if
their source-local raw Cycle numbers do not collide. Label manifests pin the mapping
file checksum; event and cycle labels preserve source IDs and add canonical
indices. Dataset Cycle joins prefer canonical identity when present and retain
source DataAsset identity for legacy multi-asset outputs. This software path
does not prove the operator's physical Cycle interpretation or enable real
multi-XLSX labels until an accepted mapping and evidence file are provided.
Never edit processed Parquet to mimic a mapping.
