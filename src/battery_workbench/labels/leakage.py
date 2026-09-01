"""Leakage-isolation group IDs and split policy (BRW-014).

Frame-level random splitting is prohibited: frames from the same cycle share
electrical state and the same SOH value, so a random row split would leak.
Group identity is deterministic over battery/experiment/cycle.
"""

from __future__ import annotations

FORBIDDEN_FEATURE_COLUMNS = (
    "waveform_rms_a_u",
    "waveform_p2p_a_u",
    "waveform_min_a_u",
    "waveform_max_a_u",
    "envelope_peak_a_u",
    "xcorr_shift_samples",
    "xcorr_peak_coefficient",
    "waveform",
    "tof_us",
    "fft_peak_hz",
)

_ALLOWED_REFERENCE_SCOPES = {
    "WITHIN_EXPERIMENT_BASELINE",
    "EXTERNAL_METADATA",
    "RPT",
    "TRAIN_ONLY_ESTIMATE",
}


def build_group_ids(
    battery_id: str,
    experiment_id: str,
    cycle_index_raw: float,
) -> dict[str, str]:
    """Deterministic leakage-isolation group IDs."""
    cycle = _cycle_token(cycle_index_raw)
    return {
        "battery_group_id": f"BG::{battery_id}",
        "experiment_group_id": f"EG::{battery_id}::{experiment_id}",
        "cycle_group_id": f"CG::{battery_id}::{experiment_id}::{cycle}",
        "label_group_id": f"LG::{battery_id}::{experiment_id}::{cycle}",
    }


def _cycle_token(cycle_index_raw: float) -> str:
    value = float(cycle_index_raw)
    return str(int(value)) if value.is_integer() else str(value)


def frame_random_split_prohibited() -> bool:
    """Fixed policy: never True-able off."""
    return True


def allowed_reference_scopes() -> set[str]:
    return set(_ALLOWED_REFERENCE_SCOPES)


def future_safe_reference_scopes() -> set[str]:
    """Scopes that never absorb held-out/test information."""
    return {"RPT", "TRAIN_ONLY_ESTIMATE", "EXTERNAL_METADATA"}


def forbidden_feature_columns() -> tuple[str, ...]:
    return FORBIDDEN_FEATURE_COLUMNS
