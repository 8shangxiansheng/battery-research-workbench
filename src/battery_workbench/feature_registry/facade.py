"""Minimal user-facing facade for physical feature activation.

Progressive prompting (spec#5): the user is asked for the sampling rate
first; only after it is supplied is the trigger/time-zero asked. The arrival
detector is an algorithm capability — users are never asked for algorithm
parameters.
"""

from __future__ import annotations

from battery_workbench.feature_registry.registry import get_missing_parameters_for

_PARAM_PROMPTS = {
    "ultrasound.sampling_rate_hz": "请输入采样频率 (MHz)",
    "ultrasound.trigger_sample_index": "请输入触发/时间零点 sample index",
}


def mhz_to_hz(mhz: float) -> float:
    return mhz * 1e6


def unverified_unlocks_nothing(verification_status: str) -> bool:
    return verification_status != "VERIFIED"


def next_user_prompt_for(
    feature_names: list[str], *, available: set[str] | None = None
) -> str | None:
    """Return the next user-facing prompt text, or None when nothing to ask.

    Only parameter prompts are produced here; the arrival detector is an
    internal algorithm capability and is never surfaced to the user.
    """
    missing = get_missing_parameters_for(feature_names, available=available)
    for param in missing:
        prompt = _PARAM_PROMPTS.get(param)
        if prompt is not None:
            return prompt
    return None
