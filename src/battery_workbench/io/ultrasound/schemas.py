from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from battery_workbench.domain.asset import DataAsset
from battery_workbench.domain.experiment import Experiment


@dataclass(frozen=True)
class ParsedUltrasoundFrame:
    source_line_index: int
    frame_index_raw: int
    unknown_field_1: str
    elapsed_time_s: float
    unknown_meta_0: str
    unknown_meta_1: str
    waveform: np.ndarray
    unknown_tail: list[str]

    @property
    def frame_index(self) -> int:
        """Backward-compatible alias for the pre-BRW-005 placeholder model."""
        return self.frame_index_raw

    @property
    def unknown_meta_pair(self) -> tuple[str, str]:
        return self.unknown_meta_0, self.unknown_meta_1


@dataclass
class UltrasoundAssetParseResult:
    battery_id: str
    asset: DataAsset
    source_path: Path
    source_sha256: str
    frames: list[ParsedUltrasoundFrame]
    warnings: list[str] = field(default_factory=list)

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def waveforms(self) -> np.ndarray:
        return np.stack([frame.waveform for frame in self.frames]).astype(np.int32, copy=False)

    @property
    def frame_index_min(self) -> int:
        return min(frame.frame_index_raw for frame in self.frames)

    @property
    def frame_index_max(self) -> int:
        return max(frame.frame_index_raw for frame in self.frames)

    @property
    def elapsed_time_min_s(self) -> float:
        return min(frame.elapsed_time_s for frame in self.frames)

    @property
    def elapsed_time_max_s(self) -> float:
        return max(frame.elapsed_time_s for frame in self.frames)

    @property
    def median_frame_interval_s(self) -> float:
        values = [frame.elapsed_time_s for frame in self.frames]
        return float(np.median(np.diff(values))) if len(values) > 1 else 0.0

    @property
    def absolute_timestamps(self) -> list[datetime | None]:
        start = self.asset.file_start_time
        if start is None:
            return [None] * len(self.frames)
        return [start + pd.Timedelta(seconds=frame.elapsed_time_s) for frame in self.frames]


@dataclass
class UltrasoundExperimentParseResult:
    experiment: Experiment
    assets: list[DataAsset]
    asset_results: list[UltrasoundAssetParseResult]
    frames: list[ParsedUltrasoundFrame]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class UltrasoundOutputManifest:
    output_dir: Path
    frames_path: Path
    waveforms_path: Path
    manifest_path: Path
