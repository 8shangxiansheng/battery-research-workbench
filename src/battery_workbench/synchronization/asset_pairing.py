"""DataAsset pairing happens at Experiment level.

An Experiment may contain:
- one or more electrical XLSX files
- one or more ultrasound TXT files

Pairing is validated from the manifest/time coverage; filenames are never treated
as the sole source of truth.
"""
