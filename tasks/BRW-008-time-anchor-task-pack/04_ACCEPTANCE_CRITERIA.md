# BRW-008 Acceptance Criteria

## Reference
- [ ] experiment window collected
- [ ] electrical coverage collected when available
- [ ] provenance retained
- [ ] conflicts not hidden

## Anchor
- [ ] per-asset candidates
- [ ] manifest anchor supported
- [ ] manual override supported or clean extension point
- [ ] missing anchor stays missing
- [ ] filename hint not auto-promoted

## Semantics
- [ ] PROVISIONAL != VERIFIED
- [ ] validated_sync remains false
- [ ] no timezone guessing
- [ ] elapsed=0 anchor distinguished from first frame

## Coverage
- [ ] candidate start/end
- [ ] start residual
- [ ] end residual
- [ ] duration residual
- [ ] overlap fraction
- [ ] configurable plausibility policy

## Multi-asset
- [ ] separate anchor per asset
- [ ] elapsed resets supported
- [ ] no cycle-based mapping

## Persistence
- [ ] time_anchors.json
- [ ] JSON report
- [ ] HTML report

## Current baseline
- [ ] U001 manifest anchor recognized
- [ ] U001 status PROVISIONAL
- [ ] coverage plausible
- [ ] validated_sync=false

## Integrity
- [ ] manifests unchanged
- [ ] electrical processed unchanged
- [ ] ultrasound processed unchanged

## Tests
- [ ] pytest
- [ ] ruff
- [ ] format
- [ ] mypy as environment permits
- [ ] git diff
