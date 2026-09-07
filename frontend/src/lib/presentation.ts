import type { ResultRecord } from "../api/client";

const names: Record<string, string> = {
  amplitude_a_u: "Amplitude", tof_us: "TOF", wave_speed_m_s: "Wave speed",
  waveform_rms_a_u: "RMS", waveform_p2p_a_u: "Peak-to-peak amplitude",
  waveform_energy_a_u: "Energy", waveform_std_a_u: "Standard deviation",
  waveform_min_a_u: "Minimum amplitude", waveform_max_a_u: "Maximum amplitude",
  envelope_peak_a_u: "Envelope peak", xcorr_shift_samples: "Relative waveform shift",
  DUMMY_MEAN: "Dummy Mean", LINEAR_REGRESSION: "Linear regression", RIDGE: "Ridge",
  RANDOM_FOREST: "Random forest", GRADIENT_BOOSTING: "Gradient boosting",
  PROVISIONAL: "Provisional timebase", READY_FOR_LIMITED_EVALUATION: "Limited evaluation",
  NOT_READY_FOR_MODEL_EVALUATION: "Not ready for evaluation", BLOCKED: "Input required",
  NOT_AVAILABLE_CURRENT_ENVIRONMENT: "Not available", AVAILABLE: "Available",
  DIRECT_CURRENT_ARTIFACT: "Current artifact", PRIOR_AUDIT: "Prior audit",
  SYNTHETIC_TEST: "Synthetic test", SOURCE_INFERENCE: "Source inference",
  DERIVED_COMPUTATION: "Derived computation", USER_PROVIDED_CONTEXT: "User provided",
};
export function displayName(value: string) { return names[value] ?? value.replaceAll("_", " ").toLowerCase(); }
export function numberText(value: unknown, digits = 2): string {
  return typeof value === "number" && Number.isFinite(value) ? new Intl.NumberFormat("en", { maximumFractionDigits: digits }).format(value) : "—";
}
// 仅比较 API 已提供、同口径的结果，不聚合或重算任何指标。
export function modelComparison(results: ResultRecord[]) {
  const macro = results.filter(r => r.result_type === "MODEL_COMPARISON");
  const dummy = macro.find(r => r.strategy === "DUMMY_MEAN" && typeof r.value === "number");
  const peers = dummy ? macro.filter(r => r.strategy !== "DUMMY_MEAN" && typeof r.value === "number" &&
    r.dataset_id === dummy.dataset_id && r.split_id === dummy.split_id && r.scope === dummy.scope && r.units === dummy.units) : [];
  const beats = dummy && peers.length ? peers.some(r => (r.value as number) < (dummy.value as number)) : null;
  return { macro, dummy, peers, beats };
}
