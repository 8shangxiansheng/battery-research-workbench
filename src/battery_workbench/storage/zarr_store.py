"""Ultrasound waveform storage.

P3/P4 will store frame x sample arrays in Zarr. PostgreSQL/SQLite stores only
metadata and references, not all waveform samples.
"""
