"""Read-only evidence checks and readiness for gated scientific capabilities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, Request

from battery_workbench.api.dependencies import get_service
from battery_workbench.api.errors import APIError, ErrorCode
from battery_workbench.api.future_contracts import (
    ExtensionReadiness,
    ExtensionReadinessEnvelope,
    TargetDatasetRequest,
    TargetSourceEvidenceValidationEnvelope,
    TargetSourceVerificationResult,
    build_extension_readiness,
)
from battery_workbench.api.routes.features_v2 import alignment_summary, list_targets
from battery_workbench.api.service import validate_id
from battery_workbench.datasets.cohort import eligible_cohort_for_experiment
from battery_workbench.domain.asset import DataAsset
from battery_workbench.io.experiment.manifest_loader import (
    data_asset_matches,
    load_batteries,
    load_data_assets,
)

router = APIRouter(tags=["scientific-resources"])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parser_manifest_source_status(
    *,
    processed_root: Path,
    battery_id: str,
    experiment_id: str,
    asset: DataAsset,
    raw_sha256: str,
) -> str:
    processed_root = Path(processed_root).resolve()
    from battery_workbench.provenance.parser_manifest import parser_output_integrity_reasons

    output_reasons = parser_output_integrity_reasons(
        processed_root, battery_id, experiment_id
    ).get(asset.modality, [])

    def require_parser_output_integrity() -> None:
        if output_reasons:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "parser output integrity is invalid for the target source modality",
                {"modality": asset.modality, "integrity_reasons": output_reasons},
            )
    manifest_path = (
        processed_root
        / asset.modality
        / battery_id
        / experiment_id
        / "parser_manifest.json"
    )
    if not manifest_path.exists() and not manifest_path.is_symlink():
        require_parser_output_integrity()
        return "NOT_AVAILABLE"
    try:
        resolved_manifest_path = manifest_path.resolve(strict=True)
        resolved_manifest_path.relative_to(processed_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "parser source manifest is missing or outside processed data",
            {"modality": asset.modality},
        ) from exc
    if not resolved_manifest_path.is_file():
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "parser source manifest is not a file",
            {"modality": asset.modality},
        )
    try:
        manifest = json.loads(resolved_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "parser source manifest is unreadable",
            {"modality": asset.modality},
        ) from exc
    if not isinstance(manifest, dict):
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "parser source manifest must contain a JSON object",
            {"modality": asset.modality},
        )
    if (
        manifest.get("battery_id") != battery_id
        or manifest.get("experiment_id") != experiment_id
    ):
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "parser source manifest identity does not match the requested experiment",
            {"asset_id": asset.asset_id},
        )
    hashes = manifest.get("source_sha256")
    if not isinstance(hashes, dict):
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "parser source manifest has no source_sha256 mapping",
            {"asset_id": asset.asset_id},
        )
    parser_sha256 = hashes.get(asset.asset_id)
    if parser_sha256 is None:
        require_parser_output_integrity()
        return "NOT_RECORDED"
    if not isinstance(parser_sha256, str) or len(parser_sha256) != 64:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "parser manifest contains an invalid source checksum",
            {"asset_id": asset.asset_id},
        )
    if parser_sha256.lower() != raw_sha256.lower():
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "parser manifest checksum does not match the current raw DataAsset checksum",
            {"asset_id": asset.asset_id},
        )

    if asset.modality == "electrical":
        details = manifest.get("source_asset_details", [])
        path_field = "relative_path"
    else:
        details = manifest.get("assets", [])
        path_field = "source_file"
    if not isinstance(details, list):
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "parser source manifest has an invalid asset provenance list",
            {"asset_id": asset.asset_id},
        )
    matching = [
        item
        for item in details
        if isinstance(item, dict) and str(item.get("asset_id")) == asset.asset_id
    ]
    if len(matching) > 1:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "parser source manifest contains duplicate asset provenance entries",
            {"asset_id": asset.asset_id},
        )
    if not matching or not matching[0].get(path_field):
        require_parser_output_integrity()
        return "CHECKSUM_VERIFIED_PATH_NOT_RECORDED"
    if str(matching[0][path_field]) != asset.relative_path.as_posix():
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "parser manifest source path does not match the registered DataAsset path",
            {"asset_id": asset.asset_id},
        )
    require_parser_output_integrity()
    return "VERIFIED"


@router.post(
    "/target-datasets/validate-source-evidence",
    response_model=TargetSourceEvidenceValidationEnvelope,
)
def validate_target_source_evidence(
    request: Request, body: TargetDatasetRequest
) -> TargetSourceEvidenceValidationEnvelope:
    """Read-only preflight for manifest identity and raw-source checksums.

    This verifies source evidence only. It does not assess scientific target
    readiness, resolve feature availability, or materialize a dataset.
    """
    service = get_service(request)
    manifest_path = service.raw_root / "manifests" / "data_assets.csv"
    if not manifest_path.is_file():
        raise APIError(
            ErrorCode.SCIENTIFIC_READINESS_BLOCKED,
            "DataAsset manifest is unavailable; target source evidence cannot be verified",
        )
    try:
        assets = load_data_assets(manifest_path)
    except (OSError, KeyError, ValueError) as exc:
        raise APIError(
            ErrorCode.INTEGRITY_ERROR,
            "DataAsset manifest could not be read consistently",
        ) from exc

    pair_assets: dict[tuple[str, str], dict[str, DataAsset]] = {}
    for battery_id, experiment_id in zip(body.battery_ids, body.experiment_ids, strict=True):
        pair = (battery_id, experiment_id)
        matched_assets = [
            asset for asset in assets if data_asset_matches(asset, battery_id, experiment_id)
        ]
        if not matched_assets:
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                "target dataset identity is not registered in the DataAsset manifest",
                {"battery_id": battery_id, "experiment_id": experiment_id},
            )
        asset_ids = [asset.asset_id for asset in matched_assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "DataAsset manifest contains duplicate DataAsset IDs for a requested experiment",
                {"battery_id": battery_id, "experiment_id": experiment_id},
            )
        pair_assets[pair] = {asset.asset_id: asset for asset in matched_assets}

    source_pairs: set[tuple[str, str]] = set()
    verified_sources: list[TargetSourceVerificationResult] = []
    raw_root = service.raw_root.resolve()
    for source in body.label_provenance.source_references:
        candidates = [
            (pair, pair_asset[source.asset_id])
            for pair, pair_asset in pair_assets.items()
            if source.asset_id in pair_asset
        ]
        path_candidates = [
            (pair, asset)
            for pair, asset in candidates
            if source.source_reference == asset.relative_path.as_posix()
        ]
        if path_candidates:
            candidates = path_candidates
        if len(candidates) != 1:
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                "target source asset must resolve to exactly one requested Battery/Experiment",
                {"asset_id": source.asset_id},
            )
        pair, asset = candidates[0]
        if asset.modality != "electrical":
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                "SOC, temperature, and SOH label sources must reference an electrical DataAsset",
                {
                    "asset_id": source.asset_id,
                    "target_id": body.target_id,
                    "observed_modality": asset.modality,
                    "expected_modality": "electrical",
                },
            )
        registered_reference = asset.relative_path.as_posix()
        if source.source_reference != registered_reference:
            raise APIError(
                ErrorCode.VALIDATION_ERROR,
                "target source reference does not match its registered DataAsset path",
                {"asset_id": source.asset_id},
            )
        relative_path = asset.relative_path
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "registered DataAsset path is not confined to data/raw",
                {"asset_id": source.asset_id},
            )
        source_path = (raw_root / relative_path).resolve()
        if not source_path.is_relative_to(raw_root) or not source_path.is_file():
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "registered target source file is missing or outside data/raw",
                {"asset_id": source.asset_id},
            )
        try:
            actual_sha256 = _sha256(source_path)
        except OSError as exc:
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "registered target source file could not be read",
                {"asset_id": source.asset_id},
            ) from exc
        if actual_sha256.lower() != source.sha256.lower():
            raise APIError(
                ErrorCode.INTEGRITY_ERROR,
                "target source checksum does not match the raw DataAsset",
                {"asset_id": source.asset_id},
            )
        source_pairs.add(pair)
        parser_provenance = _parser_manifest_source_status(
            processed_root=service.processed_root,
            battery_id=pair[0],
            experiment_id=pair[1],
            asset=asset,
            raw_sha256=actual_sha256,
        )
        verified_sources.append(
            TargetSourceVerificationResult(
                asset_id=source.asset_id,
                verified=True,
                sha256=actual_sha256,
                parser_provenance=parser_provenance,
            )
        )

    missing_pairs = sorted(set(pair_assets) - source_pairs)
    if missing_pairs:
        raise APIError(
            ErrorCode.VALIDATION_ERROR,
            "each requested Battery/Experiment requires at least one verified label source",
            {"missing_pairs": [list(pair) for pair in missing_pairs]},
        )
    return TargetSourceEvidenceValidationEnvelope(
        data={
            "status": "SOURCE_EVIDENCE_VERIFIED",
            "target_id": body.target_id,
            "verified_sources": verified_sources,
            "source_integrity": "VERIFIED",
            "label_source_semantics": "NOT_ASSESSED",
            "target_readiness": "NOT_ASSESSED",
            "feature_availability": "NOT_ASSESSED",
            "materialization_enabled": False,
        },
        meta={"read_only": True},
    )


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
    cohort = eligible_cohort_for_experiment(
        service.processed_root,
        battery_id,
        experiment_id,
        raw_root=service.raw_root,
    )
    data: ExtensionReadiness = build_extension_readiness(
        battery_id=battery_id,
        experiment_id=experiment_id,
        battery_count=battery_count,
        timebase_status=str(sync.get("timebase_status", "UNKNOWN")),
        independent_soh_states=int(soh.get("coverage", {}).get("independent_states", 0)),
        temperature_valid_count=int(temperature.get("coverage", {}).get("valid", 0)),
        temperature_range_c=temperature_range_c,
        # Temperature rows can be materialized from raw auxTemp, but this
        # experiment currently has no verified sensor location/calibration
        # evidence registry. Keep the modeling boundary closed until one exists.
        temperature_evidence_verified=False,
        model_beats_dummy=model_beats_dummy,
        has_independent_validation=False,
        eligible_cohort_battery_count=int(cohort.get("battery_count", 0)) if cohort else 0,
        eligible_cohort_id=cohort.get("cohort_dataset_id") if cohort else None,
    )
    return ExtensionReadinessEnvelope(data=data, meta={"read_only": True})
