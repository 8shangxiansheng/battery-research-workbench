"""Deterministic first-arrival detector (sample domain — no fs required).

Algorithm: ``noise_floor_threshold_v1``
  1. Robust noise floor: sigma = 0.25-quantile of |x| (signal-free majority).
  2. Threshold = 10 × sigma.
  3. Arrival = first sample where |x| exceeds the threshold for
     ``SUSTAIN_SAMPLES`` consecutive samples (spike guard).

The detector is pure sample-domain: it never needs the sampling rate and
never uses the envelope peak as the arrival. Validation is synthetic
(AGENTS.md #13): waveforms with known ground-truth arrival samples must be
hit exactly; pure noise must yield no detection.
"""

from __future__ import annotations

import numpy as np

DETECTOR_VERSION = "noise_floor_threshold_v1"
NOISE_QUANTILE = 0.25
THRESHOLD_SIGMA = 10.0
SUSTAIN_SAMPLES = 5


def detect_arrival_sample(waveform: np.ndarray) -> int | None:
    """Return the first-arrival sample index, or None when nothing is detected."""
    x = np.abs(np.asarray(waveform, dtype=float))
    if x.size < SUSTAIN_SAMPLES + 1:
        return None
    sigma = float(np.quantile(x, NOISE_QUANTILE))
    if sigma <= 0.0:
        sigma = float(np.median(x)) or 1.0
    threshold = THRESHOLD_SIGMA * sigma
    above = x > threshold
    # First index whose next SUSTAIN_SAMPLES are all above threshold.
    kernel = np.ones(SUSTAIN_SAMPLES, dtype=int)
    run = np.convolve(above.astype(int), kernel, mode="valid")
    candidates = np.flatnonzero(run == SUSTAIN_SAMPLES)
    if candidates.size == 0:
        return None
    return int(candidates[0])


def validate_arrival_detector(*, case_count: int = 12) -> dict:
    """Synthetic validation suite: exact ground-truth hits + no false alarm.

    Returns a JSON-serializable report; ``validated`` is True only when every
    case hits the known arrival exactly and the noise-only controls find
    nothing.
    """
    arrivals = np.linspace(50, 1100, case_count).astype(int).tolist()
    failed: list[dict] = []
    for i, arrival in enumerate(arrivals):
        wave = synthetic_arrival_waveform(arrival_sample=arrival, seed=100 + i)
        found = detect_arrival_sample(wave)
        if found != arrival:
            failed.append({"case": i, "expected": arrival, "found": found})
    # Noise-only controls: detection must be None.
    for i in range(3):
        rng = np.random.default_rng(500 + i)
        noise = rng.normal(0.0, 1.0, 1250)
        found = detect_arrival_sample(noise)
        if found is not None:
            failed.append({"case": f"noise_control_{i}", "expected": None, "found": found})
    return {
        "detector_version": DETECTOR_VERSION,
        "algorithm": "0.25-quantile noise floor × 10σ, 5-sample sustain",
        "case_count": case_count + 3,
        "failed_cases": failed,
        "validated": len(failed) == 0,
    }


def synthetic_arrival_waveform(
    *,
    arrival_sample: int,
    n_samples: int = 1250,
    noise_sigma: float = 1.0,
    pulse_amplitude: float = 100.0,
    seed: int = 42,
) -> np.ndarray:
    """Noise + exponentially-decaying sinusoid starting exactly at arrival_sample."""
    rng = np.random.default_rng(seed)
    t = np.arange(n_samples)
    wave = rng.normal(0.0, noise_sigma, n_samples)
    tail = t[arrival_sample:] - arrival_sample
    envelope = pulse_amplitude * np.exp(-tail / 300.0)
    # Cosine phase: full amplitude exactly at the arrival sample (a real
    # arriving pulse carries energy at onset; sin phase would start at 0).
    wave[arrival_sample:] += envelope * np.cos(2 * np.pi * 0.05 * tail)
    return wave
