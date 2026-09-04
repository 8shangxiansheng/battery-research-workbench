import itertools
import os
import statistics
from pathlib import Path

import pytest

from battery_workbench.io.electrical.custom_excel import inspect_electrical_workbook
from battery_workbench.io.ultrasound.custom_txt import iter_ultrasound_frames

DATA_DIR = os.getenv("BRW_SAMPLE_DATA_DIR")
pytestmark = pytest.mark.integration


@pytest.mark.skipif(not DATA_DIR, reason="Set BRW_SAMPLE_DATA_DIR to local raw sample directory")
def test_current_electrical_sample_contract() -> None:
    path = Path(DATA_DIR) / "小-1-1-264.xlsx"
    result = inspect_electrical_workbook(path)

    assert result.sheets["record"].rows == 39997
    assert result.sheets["cycle"].rows == 3
    assert result.sheets["step"].rows == 19
    assert result.sheets["auxTemp"].rows == 39998


@pytest.mark.skipif(not DATA_DIR, reason="Set BRW_SAMPLE_DATA_DIR to local raw sample directory")
def test_current_ultrasound_sample_contract() -> None:
    path = Path(DATA_DIR) / "export - 2024.01.06 - 21.03.01.txt"
    frames = list(iter_ultrasound_frames(path))

    assert len(frames) == 3999
    assert frames[0].frame_index == 0
    assert frames[-1].frame_index == 3998
    assert all(len(frame.waveform) == 1250 for frame in frames)

    intervals = [b.elapsed_time_s - a.elapsed_time_s for a, b in itertools.pairwise(frames)]
    assert statistics.median(intervals) == pytest.approx(10.0, abs=1e-5)
