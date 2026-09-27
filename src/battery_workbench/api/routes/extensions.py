"""Read-only readiness for scientific capabilities that are not yet enabled."""

from __future__ import annotations

from fastapi import APIRouter, Request

from battery_workbench.api.dependencies import get_service
from battery_workbench.api.future_contracts import (
    ExtensionReadiness,
    ExtensionReadinessEnvelope,
    build_extension_readiness,
)
from battery_workbench.api.routes.features_v2 import alignment_summary, list_targets
from battery_workbench.api.service import validate_id
from battery_workbench.datasets.cohort import eligible_cohort_for_experiment
from battery_workbench.io.experiment.manifest_loader import load_batteries

router = APIRouter(tags=["scientific-resources"])


@router.get(
    "/experiments/{battery_id}/{experiment_id}/extension-readiness",
    response_model=ExtensionReadinessEnvelope,
)
def extension_readiness(
    request: Request, battery_id: str, experiment_id: str
) -> ExtensionReadinessEnvelope:
    """Report solvable vs data-blocked boundaries and dormant future contracts.

    This endpoint is read-only.  Returned planned endpoints are intentionally
    not mounted until their activation gates are satisfied and implemented.
    """
    validate_id(battery_id, "battery_id")
    validate_id(experiment_id, "experiment_id")
    service = get_service(request)
    target_rows = list_targets(request, battery_id, experiment_id)["data"]["targets"]
    targets = {row["target_id"]: row for row in target_rows}
    sync = alignment_summary(request, battery_id, experiment_id)["data"]["sync_quality"]
    manifest = service.raw_root / "manifests" / "batteries.csv"
    battery_count = (
        len({item.battery_id for item in load_batteries(manifest)}) if manifest.is_file() else 0
    )
    soh = targets.get("soh_capacity_reference_percent", {})
    temperature = targets.get("temperature_c", {})
    temp_range = temperature.get("range")
    temperature_range_c = float(temp_range[1] - temp_range[0]) if temp_range else None
    results = service.get_results(battery_id, experiment_id, limit=500)
    macro = [
        row
        for row in results
        if row.get("result_type") == "MODEL_COMPARISON"
        and isinstance(row.get("value"), (int, float))
    ]
    dummy = next((row for row in macro if row.get("strategy") == "DUMMY_MEAN"), None)
    peers = [
        row
        for row in macro
        if dummy
        and row.get("strategy") != "DUMMY_MEAN"
        and row.get("dataset_id") == dummy.get("dataset_id")
        and row.get("split_id") == dummy.get("split_id")
        and row.get("scope") == dummy.get("scope")
        and row.get("units") == dummy.get("units")
    ]
    model_beats_dummy = (
        None
        if not dummy or not peers
        else any(float(row["value"]) < float(dummy["value"]) for row in peers)
    )
    cohort = eligible_cohort_for_experiment(service.processed_root, battery_id, experiment_id)
    data: ExtensionReadiness = build_extension_readiness(
        battery_id=battery_id,
        experiment_id=experiment_id,
        battery_count=battery_count,
        timebase_status=str(sync.get("timebase_status", "UNKNOWN")),
        independent_soh_states=int(soh.get("coverage", {}).get("independent_states", 0)),
        temperature_valid_count=int(temperature.get("coverage", {}).get("valid", 0)),
        temperature_range_c=temperature_range_c,
        model_beats_dummy=model_beats_dummy,
        has_independent_validation=False,
        eligible_cohort_battery_count=int(cohort.get("battery_count", 0)) if cohort else 0,
        eligible_cohort_id=cohort.get("cohort_dataset_id") if cohort else None,
    )
    return ExtensionReadinessEnvelope(data=data, meta={"read_only": True})
