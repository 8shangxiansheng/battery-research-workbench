from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from battery_workbench.domain.models import UltrasoundFrame


class UltrasoundFormatError(ValueError):
    pass


@dataclass(frozen=True)
class UltrasoundInspection:
    frame_count: int
    waveform_lengths: set[int]
    section_counts: set[int]
    first_frame_id: int
    last_frame_id: int


def parse_ultrasound_line(line: str) -> UltrasoundFrame:
    parts = line.rstrip("\n").split(";")
    if len(parts) != 6:
        raise UltrasoundFormatError(f"Expected 6 semicolon sections, got {len(parts)}")

    meta_pair = parts[3].split()
    if len(meta_pair) != 2:
        raise UltrasoundFormatError(
            f"Expected unknown_meta_pair length 2, got {len(meta_pair)}"
        )

    waveform_tokens = parts[4].split()
    if len(waveform_tokens) != 1250:
        raise UltrasoundFormatError(
            f"Expected 1250 waveform samples, got {len(waveform_tokens)}"
        )

    tail_tokens = parts[5].split()
    if len(tail_tokens) != 16:
        raise UltrasoundFormatError(
            f"Expected 16 unknown tail values, got {len(tail_tokens)}"
        )

    return UltrasoundFrame(
        frame_index=int(parts[0]),
        unknown_field_1=parts[1],
        elapsed_time_s=float(parts[2]),
        unknown_meta_pair=(meta_pair[0], meta_pair[1]),
        waveform=[int(x) for x in waveform_tokens],
        unknown_tail=tail_tokens,
    )


def iter_ultrasound_frames(path: str | Path) -> Iterator[UltrasoundFrame]:
    path = Path(path)
    with path.open("r", encoding="utf-8", errors="strict") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield parse_ultrasound_line(line)
            except Exception as exc:
                raise UltrasoundFormatError(f"Line {line_number}: {exc}") from exc


def inspect_ultrasound_txt(path: str | Path) -> UltrasoundInspection:
    frames = iter_ultrasound_frames(path)
    count = 0
    waveform_lengths: set[int] = set()
    section_counts = {6}
    first_id = None
    last_id = None

    for frame in frames:
        count += 1
        waveform_lengths.add(len(frame.waveform))
        if first_id is None:
            first_id = frame.frame_index
        last_id = frame.frame_index

    if count == 0 or first_id is None or last_id is None:
        raise UltrasoundFormatError("No frames found")

    return UltrasoundInspection(
        frame_count=count,
        waveform_lengths=waveform_lengths,
        section_counts=section_counts,
        first_frame_id=first_id,
        last_frame_id=last_id,
    )
