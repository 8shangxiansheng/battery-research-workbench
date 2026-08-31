from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from battery_workbench.io.ultrasound.schemas import ParsedUltrasoundFrame

EXPECTED_SECTIONS = 6
EXPECTED_WAVEFORM_SAMPLES = 1250
EXPECTED_TAIL_VALUES = 16


class UltrasoundFormatError(ValueError):
    """A non-empty TXT line violates the confirmed Ultrasound contract."""


@dataclass(frozen=True)
class UltrasoundInspection:
    frame_count: int
    waveform_lengths: set[int]
    section_counts: set[int]
    first_frame_id: int
    last_frame_id: int


def _error(
    message: str,
    *,
    asset_id: str,
    source_file: str | Path,
    line_number: int,
    field: str,
) -> UltrasoundFormatError:
    return UltrasoundFormatError(
        f"asset_id={asset_id} file={source_file} line={line_number} field={field}: {message}"
    )


def parse_ultrasound_line(
    line: str,
    *,
    asset_id: str = "<unknown>",
    source_file: str | Path = "<memory>",
    line_number: int = 1,
    expected_waveform_samples: int = EXPECTED_WAVEFORM_SAMPLES,
    expected_tail_values: int = EXPECTED_TAIL_VALUES,
) -> ParsedUltrasoundFrame:
    """Parse one non-empty frame without applying scientific transformations."""
    parts = line.rstrip("\r\n").split(";")
    if len(parts) != EXPECTED_SECTIONS:
        raise _error(
            f"expected {EXPECTED_SECTIONS} semicolon sections, got {len(parts)}",
            asset_id=asset_id,
            source_file=source_file,
            line_number=line_number,
            field="sections",
        )

    meta_pair = parts[3].split()
    if len(meta_pair) != 2:
        raise _error(
            f"expected 2 tokens, got {len(meta_pair)}",
            asset_id=asset_id,
            source_file=source_file,
            line_number=line_number,
            field="unknown_meta_pair",
        )

    waveform_tokens = parts[4].split()
    if len(waveform_tokens) != expected_waveform_samples:
        raise _error(
            f"expected {expected_waveform_samples} samples, got {len(waveform_tokens)}",
            asset_id=asset_id,
            source_file=source_file,
            line_number=line_number,
            field="waveform",
        )
    try:
        waveform_64 = np.asarray(waveform_tokens, dtype=np.int64)
    except ValueError as error:
        raise _error(
            f"invalid integer sample: {error}",
            asset_id=asset_id,
            source_file=source_file,
            line_number=line_number,
            field="waveform",
        ) from error
    int32 = np.iinfo(np.int32)
    if waveform_64.min() < int32.min or waveform_64.max() > int32.max:
        raise _error(
            "sample does not fit int32",
            asset_id=asset_id,
            source_file=source_file,
            line_number=line_number,
            field="waveform",
        )

    tail_tokens = parts[5].split()
    if len(tail_tokens) != expected_tail_values:
        raise _error(
            f"expected {expected_tail_values} values, got {len(tail_tokens)}",
            asset_id=asset_id,
            source_file=source_file,
            line_number=line_number,
            field="unknown_tail",
        )

    try:
        frame_index = int(parts[0].strip())
    except ValueError as error:
        raise _error(
            f"invalid integer: {parts[0]!r}",
            asset_id=asset_id,
            source_file=source_file,
            line_number=line_number,
            field="frame_index_raw",
        ) from error
    try:
        elapsed_time = float(parts[2].strip())
    except ValueError as error:
        raise _error(
            f"invalid float: {parts[2]!r}",
            asset_id=asset_id,
            source_file=source_file,
            line_number=line_number,
            field="elapsed_time_s",
        ) from error

    return ParsedUltrasoundFrame(
        source_line_index=line_number,
        frame_index_raw=frame_index,
        unknown_field_1=parts[1].strip(),
        elapsed_time_s=elapsed_time,
        unknown_meta_0=meta_pair[0],
        unknown_meta_1=meta_pair[1],
        waveform=waveform_64.astype(np.int32),
        unknown_tail=tail_tokens,
    )


def iter_ultrasound_frames(
    path: str | Path,
    *,
    asset_id: str = "<unknown>",
    expected_waveform_samples: int = EXPECTED_WAVEFORM_SAMPLES,
) -> Iterator[ParsedUltrasoundFrame]:
    source_path = Path(path)
    with source_path.open("r", encoding="utf-8", errors="strict") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            yield parse_ultrasound_line(
                line,
                asset_id=asset_id,
                source_file=source_path,
                line_number=line_number,
                expected_waveform_samples=expected_waveform_samples,
            )


def inspect_ultrasound_txt(path: str | Path) -> UltrasoundInspection:
    frames = list(iter_ultrasound_frames(path))
    if not frames:
        raise UltrasoundFormatError(f"file={path}: no frames found")
    return UltrasoundInspection(
        frame_count=len(frames),
        waveform_lengths={len(frame.waveform) for frame in frames},
        section_counts={EXPECTED_SECTIONS},
        first_frame_id=frames[0].frame_index_raw,
        last_frame_id=frames[-1].frame_index_raw,
    )
