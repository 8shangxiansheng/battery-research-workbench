from __future__ import annotations

import argparse
import itertools
import json
import statistics
from pathlib import Path

from battery_workbench.io.electrical.custom_excel import inspect_electrical_workbook
from battery_workbench.io.ultrasound.custom_txt import iter_ultrasound_frames


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--electrical", required=True)
    parser.add_argument("--ultrasound", required=True)
    args = parser.parse_args()

    electrical = inspect_electrical_workbook(Path(args.electrical))

    times: list[float] = []
    frame_count = 0
    first_id = None
    last_id = None
    for frame in iter_ultrasound_frames(Path(args.ultrasound)):
        frame_count += 1
        times.append(frame.elapsed_time_s)
        if first_id is None:
            first_id = frame.frame_index
        last_id = frame.frame_index

    intervals = [b - a for a, b in itertools.pairwise(times)]

    result = {
        "electrical": {
            "sheets": {
                name: {"rows": info.rows, "columns": info.columns}
                for name, info in electrical.sheets.items()
            }
        },
        "ultrasound": {
            "frame_count": frame_count,
            "first_frame_id": first_id,
            "last_frame_id": last_id,
            "first_elapsed_s": times[0],
            "last_elapsed_s": times[-1],
            "median_frame_interval_s": statistics.median(intervals),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
