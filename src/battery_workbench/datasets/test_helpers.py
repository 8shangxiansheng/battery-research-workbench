"""Shared synthetic-input helpers for BRW-016 dataset tests."""

from __future__ import annotations

import pandas as pd


def make_inputs(n: int = 6, n_cycles: int = 2):
    """Build minimal feature + label + cycle DataFrames."""
    cyc = [1.0 if i < n // 2 else 2.0 for i in range(n)]
    feats = pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "battery_id": ["CELL_X"] * n,
            "experiment_id": ["EXP_X"] * n,
            "ultrasound_asset_id": ["U001"] * n,
            "frame_index_raw": list(range(n)),
            "event_order_index": list(range(n)),
            "cycle_index_raw": cyc,
            "step_index_raw": [4.0] * n,
            "step_type": ["恒流放电"] * n,
            "voltage_v": [3.5] * n,
            "current_a": [1.0] * n,
            "capacity_ah": [0.5] * n,
            "temperature_c": [25.0] * n,
            "elapsed_time_s": [10.0 * i for i in range(n)],
            "sync_error_s": [0.03] * n,
            "event_quality_status": ["READY"] * n,
            "analysis_eligible": [True] * n,
            "feature_status": ["READY"] * n,
            "provisional_absolute_timestamp": pd.to_datetime(["2024-01-06T10:00:00"] * n),
            "waveform_group": ["U001/waveform"] * n,
            "waveform_row_index": list(range(n)),
            "waveform_min_a_u": [-1.0 * i for i in range(n)],
            "waveform_max_a_u": [1.0 * i for i in range(n)],
            "waveform_mean_a_u": [0.1 * i for i in range(n)],
            "waveform_std_a_u": [0.5 * i for i in range(n)],
            "waveform_rms_a_u": [0.7 * i for i in range(n)],
            "waveform_p2p_a_u": [2.0 * i for i in range(n)],
            "waveform_abs_peak_a_u": [1.5 * i for i in range(n)],
            "waveform_abs_peak_sample_index": [i for i in range(n)],
            "waveform_energy_sum_sq_a_u2": [3.0 * i for i in range(n)],
            "envelope_peak_a_u": [1.2 * i for i in range(n)],
            "envelope_peak_sample_index": [i for i in range(n)],
            "xcorr_reference_measurement_event_id": ["ME::0"] * n,
            "xcorr_shift_samples": [0] * n,
            "xcorr_peak_coefficient": [0.9] * n,
        }
    )
    soc_vals = [20.0 * i for i in range(n)]
    soh_vals = [100.0 if c == 1.0 else 99.68 for c in cyc]
    lbls = pd.DataFrame(
        {
            "measurement_event_id": [f"ME::{i}" for i in range(n)],
            "battery_id": ["CELL_X"] * n,
            "experiment_id": ["EXP_X"] * n,
            "cycle_index_raw": cyc,
            "soc_reference_percent": soc_vals,
            "soc_label_eligible": [True] * n,
            "soc_label_temporality": ["RETROSPECTIVE_SEGMENT_NORMALIZED_REFERENCE"] * n,
            "soc_reference_quality": ["VALID_REFERENCE"] * n,
            "soc_formula_version": ["0.2.0"] * n,
            "soc_anchor_quality": ["REFERENCE_PROTOCOL_ANCHOR"] * n,
            "soc_integral_unbounded_percent": [v + 0.5 for v in soc_vals],
            "soc_reference_capacity_ah": [11.04] * n,
            "soc_direction": ["DISCHARGE"] * n,
            "soh_capacity_reference_percent": soh_vals,
            "soh_label_eligible": [True] * n,
            "battery_group_id": ["BG::CELL_X"] * n,
            "experiment_group_id": ["EG::CELL_X::EXP_X"] * n,
            "cycle_group_id": [f"CG::CELL_X::EXP_X::{int(c)}" for c in cyc],
            "label_group_id": [f"LG::CELL_X::EXP_X::{int(c)}" for c in cyc],
        }
    )
    cyc_lbls = pd.DataFrame(
        {
            "battery_id": ["CELL_X"] * n_cycles,
            "experiment_id": ["EXP_X"] * n_cycles,
            "cycle_index_raw": [1.0, 2.0][:n_cycles],
            "soh_capacity_reference_percent": [100.0, 99.68][:n_cycles],
            "soh_reference_cycle_index": [1] * n_cycles,
            "soh_reference_quality": ["VALID_REFERENCE"] * n_cycles,
            "soh_label_eligible": [True] * n_cycles,
        }
    )
    return feats, lbls, cyc_lbls
