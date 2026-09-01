"""Capability assessment for BRW-015.

Evaluates what the resolved parameter set unlocks — sample-domain features,
relative time conversion, TOF development levels 0-4, wave speed, and the
capacity/label capabilities. BRW-015 evaluates capability only; it never
calculates an absolute TOF.
"""

from __future__ import annotations

TOF_LEVEL_NAMES = {
    0: "SAMPLE_DOMAIN_ONLY",
    1: "RELATIVE_TIME_CONVERSION",
    2: "RAW_TOF_DEVELOPMENT_READINESS",
    3: "RAW_ABSOLUTE_TOF_CAPABILITY",
    4: "CORRECTED_TOF_CAPABILITY",
}


def evaluate_tof_level(
    *,
    fs: float | None,
    trigger: bool,
    detector: bool,
    calibration: bool,
    fs_verified: bool = True,
) -> int:
    """TOF capability level 0-4 per the frozen contract.

    An UNVERIFIED fs behaves like no fs at all: unverified scientific-critical
    parameters never unlock physical capabilities.
    """
    if fs is None or fs <= 0 or not fs_verified:
        return 0
    if not trigger:
        return 1
    if not detector:
        return 2
    if not calibration:
        return 3
    return 4


def delay_policy_allows_component_subtraction(policy: str) -> bool:
    """SYSTEM_DELAY_TOTAL already contains the components — no re-subtraction."""
    return policy != "SYSTEM_DELAY_TOTAL"


def corrected_tof_available(*, calibration_verified: bool) -> bool:
    return calibration_verified


def wave_speed_available(
    *,
    path_length_m: float | None,
    corrected_tof_verified: bool,
    cell_thickness_m: float | None = None,
) -> bool:
    """Wave speed needs a VERIFIED acoustic path length and corrected TOF.

    Cell thickness is never silently substituted for the acoustic path.
    """
    return path_length_m is not None and path_length_m > 0 and corrected_tof_verified


def label_policy_change_allowed(*, rpt_verified: bool) -> bool:
    """An unverified RPT value cannot silently change the label policy."""
    return rpt_verified


def label_recomputation_required() -> bool:
    """The registry never requires (or performs) SOC/SOH recomputation."""
    return False


def _as_float(value: object) -> float | None:
    """Narrow an effective-parameter value to float for capability checks."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def evaluate_capabilities(
    *,
    effective: dict[str, dict],
    fs_verified_default: bool = True,
    delay_policy: str = "SYSTEM_DELAY_TOTAL",
) -> dict[str, dict]:
    """Build the full capability matrix from effective parameters.

    Each entry carries ``status`` (AVAILABLE/BLOCKED/PARTIAL), plus the
    required/missing/conflicting/unverified parameter lists that explain it.
    """

    def value(name: str) -> float | str | None:
        return effective.get(name, {}).get("value")

    def verification(name: str) -> str:
        return effective.get(name, {}).get("verification_status", "UNKNOWN")

    fs = value("ultrasound.sampling_rate_hz")
    fs_ok = fs is not None and verification("ultrasound.sampling_rate_hz") == "VERIFIED"
    trigger_ok = (
        verification("ultrasound.trigger_sample_index") == "VERIFIED"
        and value("ultrasound.trigger_sample_index") is not None
    )
    detector_ok = False  # arrival detector is NOT_SELECTED in V1
    delay_ok = (
        value("ultrasound.system_delay_s") is not None
        and verification("ultrasound.system_delay_s") == "VERIFIED"
    )
    path_ok = (
        value("experiment.ultrasound_path_length_m") is not None
        and verification("experiment.ultrasound_path_length_m") == "VERIFIED"
    )
    ref_cap = value("battery.reference_capacity_ah")

    level = evaluate_tof_level(
        fs=_as_float(fs),
        trigger=trigger_ok,
        detector=detector_ok,
        calibration=delay_ok,
        fs_verified=fs_ok or fs is None,
    )
    # Unverified fs caps the level at 0.
    if fs is not None and not fs_ok:
        level = 0

    def entry(status: str, required: list[str], missing: list[str]) -> dict:
        return {
            "status": status,
            "required_parameters": required,
            "missing_parameters": missing,
            "conflicting_parameters": [],
            "unverified_parameters": [],
        }

    return {
        "sample_time_conversion": entry(
            "AVAILABLE" if fs_ok else "BLOCKED",
            ["ultrasound.sampling_rate_hz"],
            [] if fs_ok else ["ultrasound.sampling_rate_hz"],
        ),
        "relative_shift_time_conversion": entry(
            "AVAILABLE" if fs_ok else "BLOCKED",
            ["ultrasound.sampling_rate_hz"],
            [] if fs_ok else ["ultrasound.sampling_rate_hz"],
        ),
        "raw_tof": entry(
            "AVAILABLE" if level >= 3 else "BLOCKED",
            ["ultrasound.sampling_rate_hz", "ultrasound.trigger_sample_index"],
            [
                p
                for p, ok in (
                    ("ultrasound.sampling_rate_hz", fs_ok),
                    ("ultrasound.trigger_sample_index", trigger_ok),
                )
                if not ok
            ],
        ),
        "corrected_tof": entry(
            "AVAILABLE"
            if level >= 4 and delay_policy_allows_component_subtraction(delay_policy)
            else "BLOCKED",
            ["ultrasound.system_delay_s"],
            [] if delay_ok else ["ultrasound.system_delay_s"],
        ),
        "wave_speed": entry(
            "AVAILABLE"
            if wave_speed_available(
                path_length_m=_as_float(value("experiment.ultrasound_path_length_m")),
                corrected_tof_verified=level >= 4,
            )
            else "BLOCKED",
            ["experiment.ultrasound_path_length_m", "corrected_tof"],
            [
                p
                for p, ok in (
                    ("experiment.ultrasound_path_length_m", path_ok),
                    ("corrected_tof", level >= 4),
                )
                if not ok
            ],
        ),
        "capacity_based_soc": entry(
            "AVAILABLE" if ref_cap is not None else "BLOCKED",
            ["battery.reference_capacity_ah"],
            [] if ref_cap is not None else ["battery.reference_capacity_ah"],
        ),
        "capacity_based_soh": entry(
            "AVAILABLE" if ref_cap is not None else "BLOCKED",
            ["battery.reference_capacity_ah", "labels.reference_cycle_index"],
            [],
        ),
        "online_causal_soc": entry(
            "BLOCKED",
            ["online-safe reference capacity"],
            ["online-safe reference capacity (current labels are retrospective)"],
        ),
        "retrospective_soc": entry(
            "AVAILABLE" if ref_cap is not None else "BLOCKED",
            ["battery.reference_capacity_ah"],
            [],
        ),
    }
