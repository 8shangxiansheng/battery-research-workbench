from __future__ import annotations
from pathlib import Path

from battery_workbench.io.experiment.manifest_loader import (
    load_batteries,
    load_data_assets,
    load_experiments,
)


def main() -> None:
    root = Path("data/raw/manifests")
    batteries = load_batteries(root / "batteries.csv")
    experiments = load_experiments(root / "experiments.csv")
    assets = load_data_assets(root / "data_assets.csv")

    print(f"Batteries:   {len(batteries)}")
    print(f"Experiments: {len(experiments)}")
    print(f"DataAssets:  {len(assets)}")

    for exp in experiments:
        exp_assets = [x for x in assets if x.experiment_id == exp.experiment_id]
        modalities = {}
        for asset in exp_assets:
            modalities[asset.modality] = modalities.get(asset.modality, 0) + 1
        print(
            f"- {exp.battery_id}/{exp.experiment_id}: "
            f"{modalities.get('electrical', 0)} electrical, "
            f"{modalities.get('ultrasound', 0)} ultrasound"
        )


if __name__ == "__main__":
    main()
