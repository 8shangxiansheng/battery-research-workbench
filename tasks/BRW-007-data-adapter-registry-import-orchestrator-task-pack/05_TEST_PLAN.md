# BRW-007 Test Plan

## T01 FakeAdapter
Protocol/ABC contract usable.

## T02 Registry
Register and retrieve.

## T03 Duplicate modality
Expected error.

## T04 Unknown modality
Expected error.

## T05 Default registry
Has electrical + ultrasound.

## T06 Grouping
Assets grouped by modality.

## T07 Multi-asset modality
Two electrical assets → one adapter call.

## T08 Multi-modality
Electrical + ultrasound both dispatched.

## T09 Unsupported non-strict
Expected PARTIAL.

## T10 Unsupported strict
Expected fail/exception.

## T11 One adapter fails
Other success retained.

## T12 All success
Expected SUCCESS.

## T13 Existing outputs
No overwrite by default.

## T14 Explicit overwrite
Only when requested.

## T15 Plan only
No parser execution.

## T16 Provenance
Correct IDs/adapters/paths.

## T17 Real CELL_001 plan
E001 electrical, U001 ultrasound.

## T18 Parser regression
Existing parser integration tests unchanged/pass.
