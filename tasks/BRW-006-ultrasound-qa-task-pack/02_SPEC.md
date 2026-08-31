# BRW-006 Functional Specification

## Input boundary

```text
BRW-005: frames.parquet + waveforms.zarr + parser_manifest
↓
BRW-006 QA
```

QA 不是第二个 TXT parser。

## Public API

```python
run_ultrasound_qa(
    battery_id: str,
    experiment_id: str,
    input_dir: Path,
    artifact_dir: Path,
    config: UltrasoundQAConfig,
) -> UltrasoundQAReport
```

## QA domains

1. Structural consistency
2. Provenance
3. Temporal quality
4. Frame-level waveform quality
5. Cross-frame stability
6. Anomaly detection
7. Artifact generation

## QA vs feature engineering

BRW-006 可以计算 RMS/P2P/DC/correlation，但只用于 QA；不生成正式科学特征数据集。
