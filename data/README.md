# Data Policy

- `raw/`: immutable user/source data; excluded from Git.
- `processed/`: normalized Parquet/Zarr outputs; reproducible from raw + config.
- `features/`: versioned feature tables; reproducible from processed data.
- `demo/`: only tiny, non-sensitive fixtures allowed in Git.

Do not copy full research raw data into the GitHub repository.
