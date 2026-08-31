# BRW-010 Agent Handoff

## Status
PASS / PARTIAL / FAIL

## Files changed

## Inputs

Ultrasound rows:
Electrical rows:
Electrical timestamp column:
Electrical locator:

## Matching policy

Method:
Max error:
Tie tolerance:
Ambiguous selection:

## Electrical timestamp QA

Median positive interval:
Min:
Max:
Duplicate rows:
Duplicate groups:

## Match result

Unique:
Ambiguous:
Out of tolerance:
Timestamp unavailable:
No candidate:

## Sync error

Min:
Median:
P95:
Max:

## Ambiguity audit

| Frame | Ultrasound timestamp | Error | Candidate timestamps | Candidate records | Boundary | Type |
|---|---|---:|---:|---:|---|---|
| | | | | | | |

## Golden frames

| Frame | Electrical timestamp | Error | Candidates | Status |
|---|---|---:|---:|---|
| 0 | | | | |
| 1000 | | | | |
| 2000 | | | | |
| 3000 | | | | |
| 3998 | | | | |

## Outputs

Aligned:
Candidates:
Manifest:
Report:
Figures:

## Input integrity

## Tests

pytest:
coverage:
ruff:
format:
mypy:
git diff:

## Scientific semantics

matching_performed:
validated_sync:
anchor_status:

## Scope confirmation
