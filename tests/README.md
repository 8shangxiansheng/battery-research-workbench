# Test Strategy — V1.1

## Unit
- Manifest hierarchy
- Registry lookup
- timestamp conversion
- nearest-time alignment
- boundary detection
- sync quality
- synthetic scientific algorithms

## Golden
Parser-specific known slices/values from approved raw inputs.

## Integration
Real XLSX/TXT contracts. Raw files remain outside Git.

## Synchronization Acceptance Gate
For the current paired experiment:
- absolute time mapping validated
- first/middle/last frames manually checked
- target match rate > 99%
- `sync_error_s` persisted
- cycle/step labels mapped only after time alignment
