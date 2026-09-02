# BRW-003–021 Acceptance Audit

Date: 2026-09-02

## Verdict

**BLOCK** — 571 checklist items were reviewed; 550 have direct code, test, or
materialized-artifact evidence and were checked. 21 remain open. The blocking
functional gap is in BRW-010 multi-electrical-asset identity/boundary handling.
The remaining open items are repository quality-gate failures.

## Evidence used

- Source implementations under `src/battery_workbench/`.
- Unit and real-data integration tests under `tests/`.
- Current CELL_001 / EXP_001 processed outputs and artifacts.
- Full suite: 686 collected, 684 passed, 2 skipped.
- `git diff --check`: passed before checklist edits.
- Repository Ruff: failed with one `RUF007` finding.
- Repository format check: failed for three files.
- Repository mypy: failed with three environment/configuration errors.

## Task summary

| Task | Checked | Total | Open | Status |
|---|---:|---:|---:|---|
| BRW-003 | 36 | 37 | 1 | WARN |
| BRW-004 | 55 | 56 | 1 | WARN |
| BRW-005 | 53 | 56 | 3 | WARN |
| BRW-006 | 15 | 16 | 1 | WARN |
| BRW-007 | 47 | 49 | 2 | WARN |
| BRW-008 | 36 | 37 | 1 | WARN |
| BRW-009 | 41 | 41 | 0 | PASS |
| BRW-010 | 42 | 48 | 6 | BLOCK |
| BRW-011 | 24 | 25 | 1 | WARN |
| BRW-012 | 18 | 19 | 1 | WARN |
| BRW-013 | 26 | 27 | 1 | WARN |
| BRW-014 | 19 | 20 | 1 | WARN |
| BRW-015 | 17 | 18 | 1 | WARN |
| BRW-016 | 15 | 16 | 1 | WARN |
| BRW-017 registry retrofit | 15 | 15 | 0 | PASS |
| BRW-017 V2 | 19 | 19 | 0 | PASS |
| BRW-018 | 20 | 20 | 0 | PASS |
| BRW-019 | 19 | 19 | 0 | PASS |
| BRW-020 | 14 | 14 | 0 | PASS |
| BRW-021 | 19 | 19 | 0 | PASS |

## Blocking functional finding

### BRW-010 loses selected electrical asset identity

`align_frames()` builds aligned rows without `electrical_asset_id`. On a unique
match it copies only `locator` and `timestamp` from the selected electrical
record. The service later attempts boundary lookup using
`(electrical_asset_id, electrical_record_locator)`, so `asset` is always absent
and the boundary flag remains false.

Current real output confirms:

- 3,999 aligned rows;
- 3,995 `MATCHED_UNIQUE` rows;
- no `electrical_asset_id` column;
- zero `boundary_flag=true` rows.

Open BRW-010 criteria:

- duplicate boundary detection;
- cycle/step transition diagnostic;
- electrical locators traceable;
- multi electrical;
- asset identity preserved;
- mypy as environment permits.

Recommended source/test changes:

- `src/battery_workbench/synchronization/sync_service.py`: persist the selected
  electrical asset ID and use it in boundary mapping.
- `src/battery_workbench/synchronization/sync_schemas.py`: freeze the aligned
  electrical asset identity contract.
- `tests/unit/test_sync_alignment.py`: assert selected asset ID and composite
  locator behavior.
- `tests/unit/test_sync_boundary.py`: cover service-level boundary propagation.
- Add a multi-electrical-asset integration test with overlapping row locators.

## Quality-gate findings

### Ruff

One repository-wide failure:

- `tests/integration/test_current_user_samples.py:37` — `RUF007`, replace
  successive-pair `zip()` with `itertools.pairwise()`.

This leaves BRW-003 and BRW-005 generic Ruff criteria open.

### Format

Three files would be reformatted:

- `src/battery_workbench/io/experiment/discovery.py`;
- `src/battery_workbench/registry/asset_registry.py`;
- `tests/integration/test_current_user_samples.py`.

This leaves BRW-005 and BRW-007 format criteria open.

### mypy

Task-scope and repository-wide mypy are blocked by the same toolchain issues:

- missing stubs for `scipy.signal` in `features/envelope.py` and
  `features/xcorr.py`;
- NumPy's installed stubs use Python 3.12+ type syntax while project mypy is
  configured for Python 3.11.

Affected open criteria are the explicit or combined mypy gates in BRW-004,
BRW-005, BRW-006, BRW-007, BRW-008, BRW-010, BRW-011, BRW-012, BRW-013,
BRW-014, BRW-015, and BRW-016.

## Fully accepted task packs

The current evidence closes every checklist item for BRW-009, both BRW-017
packs, BRW-018, BRW-019, BRW-020, and BRW-021. Real-data evidence includes the
timestamp outputs, feature/label/dataset/gate outputs, orchestrator Plan A/B/C
demo, grouped-split demo, and exploratory/ML-safe feature-analysis demo.

## Checklist update policy

Only criteria with direct source, passing-test, or current materialized-artifact
evidence were checked. Combined quality criteria remain open when any named
gate fails. No production source code or processed/raw data was modified during
this audit.
