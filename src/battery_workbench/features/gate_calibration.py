"""BRW-013X V2.2 — Gate calibration, feature-gate binding, extraction profiles.

Gate Calibration (§112–119):
- One-time calibration per battery/probe/acquisition configuration on a small
  deterministic representative subset (default 24–40 frames).
- Calibration frame selection NEVER uses SOC correlation, model score,
  held-out residuals, or target association (predeclared protocol basis only).
- Frozen GateCalibrationRecord with full provenance; configuration change
  forces recalibration.
- Per-frame adaptive gates are EXPLORATORY_ONLY by default.

FeatureGateBindingRegistry (§120):
- Source-backed default bindings; generic TD/FD restricted to
  FULL_WAVEFORM / USER_SELECTED_EXPLICIT_GATE.
- Default extraction policy: extract_all_features_on_all_gates = false;
  an explicit feature profile is REQUIRED.

Smoothing policy (§136–137):
- RAW variant: predictor_eligible per normal policy.
- SOURCE_MOVMEAN5 variant: predictor_eligible = False (EXPLORATORY /
  SOURCE_PARITY) — a centered 5-point window can cross split boundaries.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from battery_workbench.features.physical_v2 import GATE_TEMPLATES

CALIBRATION_POLICY_ID = "GATE_CALIBRATION_POLICY_V1"
BINDING_REGISTRY_VERSION = "FEATURE_GATE_BINDINGS_V1"
JOIN_POLICY_ID = "FEATURE_STATE_JOIN_POLICY_V1"
CORRELATION_POLICY_ID = "FEATURE_STATE_CORRELATION_POLICY_V1"
SMOOTHING_POLICY_ID = "SOURCE_MOVMEAN5_EXPLORATORY_POLICY_V1"

DEFAULT_CALIBRATION_FRAME_COUNT = 32
MIN_CALIBRATION_FRAMES = 24
MAX_CALIBRATION_FRAMES = 40

CalibrationBasis = Literal[
    "PREDECLARED_PROTOCOL_GATE",
    "EXTERNAL_CALIBRATION_DATA",
    "TRAIN_ONLY_CALIBRATED",
    "USER_CONFIRMED_PHYSICAL_MORPHOLOGY",
]
AdaptiveStatus = Literal["FIXED_EXPERIMENT_LEVEL", "EXPLORATORY_ONLY"]


# ---------------------------------------------------------------------------
# Deterministic calibration frame selection
# ---------------------------------------------------------------------------


def select_calibration_frames(
    n_total_frames: int,
    *,
    n_frames: int = DEFAULT_CALIBRATION_FRAME_COUNT,
    protocol_segments: int = 6,
) -> list[int]:
    """Deterministic, target-blind coverage selection over source frame order.

    Splits source order into ``protocol_segments`` segments (proxy for
    charge/discharge/rest protocol phases and late-experiment drift check)
    and picks evenly spaced frames inside each segment. No feature values,
    targets, or model scores are consulted.
    """
    if n_total_frames <= 0:
        raise ValueError("n_total_frames must be positive")
    n_frames = max(MIN_CALIBRATION_FRAMES, min(n_frames, MAX_CALIBRATION_FRAMES))
    n_frames = min(n_frames, n_total_frames)
    segments = min(protocol_segments, n_total_frames)
    per_seg = n_frames // segments
    remainder = n_frames % segments

    chosen: list[int] = []
    start = 0
    for seg in range(segments):
        seg_end = (n_total_frames * (seg + 1)) // segments
        count = per_seg + (1 if seg < remainder else 0)
        if count == 0:
            continue
        positions = np.linspace(start, max(start, seg_end - 1), count)
        for p in positions:
            idx = round(int(p))  # positions are float but integral-valued
            if idx not in chosen:
                chosen.append(idx)
        start = seg_end
    return sorted(set(chosen))[:n_frames]


class GateCalibrationRecord(BaseModel):
    """Frozen, versioned calibration record (§118)."""

    gate_calibration_id: str
    calibration_policy_id: str = CALIBRATION_POLICY_ID
    gate_template_id: str
    battery_id: str
    experiment_id: str
    probe_config_id: str
    acquisition_config_id: str
    source_formula_id: str
    calibration_frame_ids: list[int]
    calibration_basis: CalibrationBasis
    start_frame: int
    end_frame: int
    confirmed_by: str
    status: Literal["DRAFT", "FROZEN"] = "DRAFT"
    version: int = 1
    confirmed_at: str | None = None
    notes: str = ""

    def freeze(self, confirmed_at: str) -> GateCalibrationRecord:
        if self.status == "FROZEN":
            raise ValueError("record already frozen")
        return self.model_copy(update={"status": "FROZEN", "confirmed_at": confirmed_at})


def configuration_fingerprint(
    *, battery_id: str, probe_config_id: str, acquisition_config_id: str
) -> str:
    return f"{battery_id}|{probe_config_id}|{acquisition_config_id}"


def requires_recalibration(
    record: GateCalibrationRecord,
    *,
    battery_id: str,
    probe_config_id: str,
    acquisition_config_id: str,
) -> bool:
    """§C04 — changed probe/battery configuration forces recalibration."""
    return record and configuration_fingerprint(
        battery_id=record.battery_id,
        probe_config_id=record.probe_config_id,
        acquisition_config_id=record.acquisition_config_id,
    ) != configuration_fingerprint(
        battery_id=battery_id,
        probe_config_id=probe_config_id,
        acquisition_config_id=acquisition_config_id,
    )


def assert_target_blind_selection(frame_ids: list[int], *, basis: str) -> None:
    """C24 guard — target-informed calibration bases are forbidden."""
    forbidden = {"SOC_CORRELATION", "MODEL_SCORE", "HELD_OUT_RESIDUAL", "TARGET_OPTIMIZED"}
    if basis in forbidden:
        raise ValueError(
            f"calibration basis {basis} is target-informed and forbidden "
            f"for ML-safe evaluation"
        )


# ---------------------------------------------------------------------------
# Feature-Gate Binding Registry (§120, task pack 37)
# ---------------------------------------------------------------------------


class FeatureGateBinding(BaseModel):
    feature_code: str
    required_gates: list[str]
    role_en: str
    role_zh: str


#: Source-backed default bindings.
DEFAULT_BINDINGS: tuple[FeatureGateBinding, ...] = (
    FeatureGateBinding(
        feature_code="BOTTOM_AMP", required_gates=["BOTTOM_AMPLITUDE_GATE"],
        role_en="Bottom-wave Amplitude", role_zh="底波幅值",
    ),
    FeatureGateBinding(
        feature_code="SWA", required_gates=["SWA_SURFACE_GATE"],
        role_en="Surface Wave Amplitude", role_zh="表面波幅值",
    ),
    FeatureGateBinding(
        feature_code="TOF_XCORR",
        required_gates=["TOF_SURFACE_REFERENCE_GATE", "TOF_BOTTOM_GATE"],
        role_en="Surface-Bottom XCorr TOF", role_zh="表面波-底波互相关TOF",
    ),
    FeatureGateBinding(
        feature_code="ATTENUATION", required_gates=["ATTENUATION_BOTTOM_GATE"],
        role_en="Bottom-wave Attenuation", role_zh="底波衰减",
    ),
    FeatureGateBinding(
        feature_code="BPS", required_gates=["BPS_BOTTOM_GATE"],
        role_en="Bottom-wave Phase Shift", role_zh="底波相移",
    ),
)

_TEMPLATE_IDS = {t.gate_template_id for t in GATE_TEMPLATES}


class FeatureGateBindingRegistry:
    """Versioned registry of feature→gate bindings + generic scope rules."""

    version: str = BINDING_REGISTRY_VERSION

    def __init__(self) -> None:
        self._bindings = {b.feature_code: b for b in DEFAULT_BINDINGS}

    def binding_for(self, feature_code: str) -> FeatureGateBinding:
        return self._bindings[feature_code]

    def codes(self) -> list[str]:
        return list(self._bindings)

    def validate_gates_exist(self) -> None:
        for b in self._bindings.values():
            for g in b.required_gates:
                if g not in _TEMPLATE_IDS:
                    raise ValueError(f"unknown gate template: {g}")

    def generic_allowed_scopes(self, family: str) -> list[str]:
        """Generic TD/FD statistics: FULL_WAVEFORM or explicit user gate only."""
        return ["FULL_WAVEFORM", "USER_SELECTED_EXPLICIT_GATE"]


# ---------------------------------------------------------------------------
# Feature extraction profiles (§121, C07)
# ---------------------------------------------------------------------------


class FeatureExtractionProfile(BaseModel):
    """Explicit profile — the workbench never extracts every feature on every
    gate by default."""

    profile_id: str
    feature_codes: list[str]
    gate_ids: list[str]
    description: str = ""
    predictor_eligible_default: bool = True

    def validate_against_bindings(self, registry: FeatureGateBindingRegistry) -> None:
        for code in self.feature_codes:
            try:
                binding = registry.binding_for(code)
            except KeyError:
                continue  # generic TD/FD code — scopes governed by profile
            missing = [g for g in binding.required_gates if g not in self.gate_ids]
            if missing:
                raise ValueError(
                    f"profile {self.profile_id}: feature {code} requires gates "
                    f"{binding.required_gates}, missing {missing}"
                )


def block_all_features_all_gates(feature_codes: list[str], gate_ids: list[str]) -> None:
    """C07 guard — refuse the default all-features × all-gates explosion."""
    if len(feature_codes) > 33 and len(gate_ids) > 6:
        raise ValueError(
            "refusing to extract all features on all gates; "
            "an explicit feature profile is required"
        )


# ---------------------------------------------------------------------------
# Smoothing eligibility policy (§136–137, C21–C23)
# ---------------------------------------------------------------------------


def variant_predictor_eligible(variant: str) -> bool:
    if variant == "RAW":
        return True
    if variant in ("SOURCE_MOVMEAN5", "MOVMEAN_5_SOURCE_ORDER"):
        return False  # EXPLORATORY / SOURCE_PARITY by default
    raise ValueError(f"unknown variant: {variant}")


def smoothing_split_boundary_warning(variant: str, cycle_ids: list[Any]) -> str | None:
    """C23 — a centered 5-point window near a cycle boundary can mix
    neighboring held-out cycle samples; smoothed predictors are not ML-safe."""
    if variant in ("SOURCE_MOVMEAN5", "MOVMEAN_5_SOURCE_ORDER") and len(cycle_ids) > 1:
        return (
            "SOURCE_MOVMEAN5 smoothing window can cross cycle boundaries; "
            "not eligible as an ML-safe predictor (SOURCE_MOVMEAN5_EXPLORATORY_POLICY_V1)"
        )
    return None

# ---------------------------------------------------------------------------
# BRW-017R2 — TOF gate bindings (canonical envelope-peak method)
# ---------------------------------------------------------------------------

TOF_GATE_BINDINGS_VERSION = "TOF_GATE_BINDINGS_V1"
TOF_DEFINITION_VERSION = "0.3.0"
TOF_POLICY_VERSION = "ENVELOPE_PEAK_V1"
CANONICAL_TOF_METHOD = "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1"


class TOFGateBinding(BaseModel):
    role: Literal["surface", "bottom"]
    gate_id: str
    matlab_range: str
    python_start: int
    python_end_exclusive: int
    length_samples: int


TOF_GATE_BINDINGS: dict[str, TOFGateBinding] = {
    "surface": TOFGateBinding(
        role="surface", gate_id="TOF_SURFACE_PEAK_GATE",
        matlab_range="60:260", python_start=59, python_end_exclusive=260,
        length_samples=201,
    ),
    "bottom": TOFGateBinding(
        role="bottom", gate_id="TOF_BOTTOM_PEAK_GATE",
        matlab_range="750:1200", python_start=749, python_end_exclusive=1200,
        length_samples=451,
    ),
}


def tof_gate_bindings() -> dict[str, TOFGateBinding]:
    """Source templates — NOT universal constants; experiments must freeze a
    GateCalibrationRecord per gate before canonical TOF activates."""
    return dict(TOF_GATE_BINDINGS)


class TOFReadiness(BaseModel):
    level: int  # 0..3 per task pack §E (4 = optional corrected variant)
    level_name: str
    fs_verified: bool = False
    surface_gate_calibrated: bool = False
    bottom_gate_calibrated: bool = False
    ready: bool = False
    missing: list[str] = Field(default_factory=list)


def evaluate_tof_readiness(
    *,
    sampling_rate_hz: float | None,
    fs_verified: bool,
    surface_gate_calibrated: bool,
    bottom_gate_calibrated: bool,
) -> TOFReadiness:
    """Canonical envelope-peak readiness ladder (fs alone never activates)."""
    missing: list[str] = []
    if sampling_rate_hz is None or sampling_rate_hz <= 0 or not fs_verified:
        missing.append("SAMPLING_RATE_VERIFIED")
    if not surface_gate_calibrated:
        missing.append("SURFACE_TOF_GATE_CALIBRATED")
    if not bottom_gate_calibrated:
        missing.append("BOTTOM_TOF_GATE_CALIBRATED")
    if not missing:
        return TOFReadiness(
            level=2, level_name="FS_AND_BOTH_GATES_CALIBRATED",
            fs_verified=True, surface_gate_calibrated=True,
            bottom_gate_calibrated=True, ready=True,
        )
    if len(missing) == 1 and missing[0] == "SAMPLING_RATE_VERIFIED":
        return TOFReadiness(
            level=1, level_name="TIME_CONVERSION_ONLY",
            surface_gate_calibrated=surface_gate_calibrated,
            bottom_gate_calibrated=bottom_gate_calibrated,
            missing=missing,
        )
    return TOFReadiness(level=0, level_name="NO_FS", missing=missing)
