# Future Scientific Extension Contracts

The current RC1 evidence cannot make missing batteries, temperature channels,
independent SOH states, or an independently grouped validation set appear.
Those are evidence constraints, not parser defects. The workbench therefore
keeps these capabilities disabled while publishing a read-only readiness
surface:

```http
GET /api/v1/experiments/{battery_id}/{experiment_id}/extension-readiness
```

The response separates `BLOCKED_BY_DATA`, `BLOCKED_BY_VALIDATION`,
`NOT_IMPLEMENTED`, `PARTIALLY_READY`, and `READY`. It includes observed counts,
requirements, and JSON Schemas for four dormant contracts. A contract being
visible does not mean its planned write endpoint exists or is authorized.

## Dormant contracts

| Contract | Planned endpoint (not mounted) | Activation gate |
|---|---|---|
| `timebase-validation/1.0` | `POST /api/v1/timebase-validations` | per-asset absolute anchors, timezone, source evidence, error audit |
| `cohort-dataset/1.0` | `POST /api/v1/cohort-datasets` | at least two independent batteries, harmonized feature and target definitions |
| `target-dataset/1.0` | `POST /api/v1/target-datasets` | target-specific grain and independent-state threshold |
| `tuning-study/1.0` | `POST /api/v1/tuning-studies` | independent `VALIDATION`, untouched `HELD_OUT`, nested grouped selection |

## Scientific rules

- Cross-battery evaluation uses `battery_id` as the outer group. Random frame,
  row, MeasurementEvent, or SOC-bin splitting remains prohibited.
- SOH targets use cycle/battery-level independent states; frame rows are not
  counted as additional health states.
- Temperature requires a measured channel, audited coverage, and useful
  observed variation. It is never inferred from ultrasound.
- Tuning never reads the outer held-out target. Feature selection and search
  happen inside the training data with an independent grouped validation role.
- Failing to beat Dummy is an honest result, not an interface activation gate.
  More flexible models do not justify tuning without valid evaluation data.

The executable Pydantic contracts live in
`src/battery_workbench/api/future_contracts.py`; frontend consumers use the
typed `getExtensionReadiness` client method. When a future task implements a
write path, it must reuse the matching schema/version, add artifact identity
and provenance, and explicitly flip the descriptor's `enabled` state only
after its activation gate has tests and real-data evidence.
