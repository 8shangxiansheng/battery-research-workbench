# BRW-007 Acceptance Criteria

## Adapter
- [ ] unified interface
- [ ] experiment+modality+multi-asset granularity
- [ ] no parser duplication

## Registry
- [ ] register
- [ ] get
- [ ] has
- [ ] modalities
- [ ] duplicate registration error
- [ ] unknown modality error
- [ ] default electrical + ultrasound

## Import Plan
- [ ] grouped assets
- [ ] resolved adapters
- [ ] expected outputs
- [ ] unsupported modalities
- [ ] no parser execution

## Importer
- [ ] resolves battery
- [ ] resolves experiment
- [ ] resolves assets
- [ ] modality filtering
- [ ] group by modality
- [ ] dispatches once per modality
- [ ] collects results

## Failure policy
- [ ] partial success supported
- [ ] strict/non-strict behavior defined
- [ ] unsupported modality explicit
- [ ] adapter failure isolated

## Existing outputs
- [ ] overwrite=False safe
- [ ] no silent overwrite
- [ ] overwrite=True explicit

## Provenance
- [ ] battery
- [ ] experiment
- [ ] modality
- [ ] asset IDs
- [ ] adapter name/version
- [ ] outputs

## Real baseline
- [ ] E001 → ElectricalAdapter
- [ ] U001 → UltrasoundAdapter

## Regression
- [ ] BRW-003 unaffected
- [ ] BRW-005 unaffected
- [ ] full pytest passes
- [ ] ruff passes
- [ ] format passes
- [ ] mypy passes
- [ ] git diff check passes

## Scope
- [ ] no sync
- [ ] no new parser
- [ ] no QA rewrite
- [ ] no ML
- [ ] no Agent/UI
