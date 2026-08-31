# Output Contract

## Directory

```text
data/processed/electrical/{battery_id}/{experiment_id}/
```

## Required

```text
records.parquet
cycles.parquet
steps.parquet
parser_manifest.json
```

## Conditional

```text
aux_temperature.parquet
aux_voltage.parquet
```

## records.parquet minimum provenance

```text
battery_id
experiment_id
electrical_asset_id
source_file
source_sheet
source_row_index
```

## Data types

Prefer:

- IDs / step types: string / nullable integer
- physical values: float64 or appropriate nullable numeric
- timestamp: `datetime64[ns]`
- no mixed object columns for core numeric fields

## Parquet invariant

```python
df_written.equals(df_read_back)
```

does not have to be byte-identical, but:

- row count
- canonical columns
- IDs
- timestamps
- core numeric values

must remain equivalent.
