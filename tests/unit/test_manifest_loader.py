from pathlib import Path

from battery_workbench.io.experiment.manifest_loader import (
    load_batteries,
    load_data_assets,
    load_experiments,
)


def test_manifest_hierarchy(tmp_path: Path) -> None:
    batteries = tmp_path / "batteries.csv"
    experiments = tmp_path / "experiments.csv"
    assets = tmp_path / "data_assets.csv"

    batteries.write_text(
        "battery_id,chemistry,nominal_capacity_ah,notes\nCELL_A,NMC,5.0,test\n",
        encoding="utf-8",
    )
    experiments.write_text(
        "experiment_id,battery_id,start_time,end_time,protocol,notes\n"
        "EXP_A,CELL_A,2024-01-01 10:00:00,2024-01-01 12:00:00,cycling,test\n",
        encoding="utf-8",
    )
    assets.write_text(
        "asset_id,experiment_id,modality,relative_path,file_start_time,file_end_time,"
        "parser_name,parser_version\n"
        "E1,EXP_A,electrical,batteries/CELL_A/EXP_A/electrical/a.xlsx,,,custom_excel,0.1\n"
        "U1,EXP_A,ultrasound,batteries/CELL_A/EXP_A/ultrasound/u1.txt,"
        "2024-01-01 10:00:00,,custom_txt,0.1\n"
        "U2,EXP_A,ultrasound,batteries/CELL_A/EXP_A/ultrasound/u2.txt,"
        "2024-01-01 11:00:00,,custom_txt,0.1\n",
        encoding="utf-8",
    )

    b = load_batteries(batteries)
    e = load_experiments(experiments)
    a = load_data_assets(assets)

    assert b[0].battery_id == "CELL_A"
    assert e[0].battery_id == "CELL_A"
    assert len(a) == 3
    assert [x.asset_id for x in a if x.modality == "ultrasound"] == ["U1", "U2"]
