# BRW-003 Functional Specification

## Input

Source of truth:

```text
data/raw/manifests/data_assets.csv
```

Filter:

```text
modality == electrical
```

Each DataAsset references one immutable `.xlsx`.

## Core API

Recommended minimum:

```python
parse_electrical_asset(asset: DataAsset, raw_root: Path) -> ElectricalParseResult

parse_electrical_experiment(
    experiment: Experiment,
    assets: list[DataAsset],
    raw_root: Path,
) -> ElectricalExperimentParseResult

write_electrical_experiment(
    result: ElectricalExperimentParseResult,
    output_root: Path,
) -> ElectricalOutputManifest
```

## Important separation

`custom_excel.py`

> How do I read this workbook format?

`service.py`

> Which assets belong to this Experiment and how are outputs combined?

Do not mix those responsibilities.

## Canonical provenance fields

Every standardized row should be able to answer:

```text
Which battery?
Which experiment?
Which XLSX DataAsset?
Which original sheet?
Which original row?
```

## Cycle identity

Keep:

```text
cycle_index_raw
step_index_raw
```

Do not create artificial battery-global cycle numbering in BRW-003.

If needed later, synchronization/analysis layer can create a higher-level canonical cycle ID.
