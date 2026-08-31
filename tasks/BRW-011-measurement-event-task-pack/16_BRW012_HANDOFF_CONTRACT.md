# BRW-012 Handoff Contract

After BRW-011, scientific analysis should consume:

```text
measurement_events.parquet
```

Future ConditionSlice / FeatureSet / CorrelationAnalysis should use `analysis_eligible == true` by default while retaining ambiguous/ineligible events for audit.

BRW-012 must not redo synchronization.
