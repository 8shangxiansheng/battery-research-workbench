# BRW-004 Functional Specification

## Input boundary

```text
BRW-003 Parser
↓
Standardized Parquet + parser_manifest
↓
BRW-004 QA
```

QA 不是第二个 parser。

## Public API

推荐：

```python
run_electrical_qa(
    battery_id: str,
    experiment_id: str,
    input_dir: Path,
    artifact_dir: Path,
    config: ElectricalQAConfig,
) -> ElectricalQAReport
```

## QA domains

1. Schema
2. Completeness
3. Temporal
4. Cycle
5. Step
6. Physical sanity
7. Cross-table
8. Artifact generation

## Invariant

BRW-004 不修改：

```text
records.parquet
cycles.parquet
steps.parquet
aux_*.parquet
```
