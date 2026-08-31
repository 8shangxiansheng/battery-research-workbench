from __future__ import annotations

from itertools import pairwise

from battery_workbench.io.ultrasound.custom_txt import UltrasoundFormatError
from battery_workbench.io.ultrasound.schemas import ParsedUltrasoundFrame


def validate_frame_sequence(
    frames: list[ParsedUltrasoundFrame],
    *,
    asset_id: str,
    source_file: str,
) -> list[str]:
    if not frames:
        raise UltrasoundFormatError(
            f"asset_id={asset_id} file={source_file} field=frames: no non-empty frames found"
        )
    warnings: list[str] = []
    frame_ids = [frame.frame_index_raw for frame in frames]
    elapsed = [frame.elapsed_time_s for frame in frames]
    if any(current <= previous for previous, current in pairwise(frame_ids)):
        raise UltrasoundFormatError(
            f"asset_id={asset_id} file={source_file} field=frame_index_raw: "
            "values must be strictly increasing"
        )
    if any(current <= previous for previous, current in pairwise(elapsed)):
        raise UltrasoundFormatError(
            f"asset_id={asset_id} file={source_file} field=elapsed_time_s: "
            "values must be strictly increasing"
        )
    expected = list(range(frame_ids[0], frame_ids[0] + len(frame_ids)))
    if frame_ids != expected:
        warnings.append(
            f"asset_id={asset_id} file={source_file}: frame_index_raw is not contiguous; "
            "raw IDs were preserved"
        )
    return warnings
