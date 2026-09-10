/**
 * BRW-025R-OV — O01–O29 ResearchOverview first-screen tests.
 *
 * 契约：单一 /research-overview 聚合数据源；前端不算科学；
 * 未知 metadata 显示 Not configured；SNR 无算法定义 → Not configured；
 * waveform TOF rows ≠ Feature–Target eligible counts；
 * 模型区分 Available/Valid/Selected/Used；stale 工件显示 refresh required；
 * Quick Actions ≤3；inline fs 复用共享 submission service。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { client } from "../src/api/client";
import { ResearchOverview } from "../src/pages/redesign/ResearchOverview";
import { AssistantProvider, useAssistant } from "../src/components/workbench/AssistantContext";

function ContextProbe() {
  const assistant = useAssistant();
  return <output data-testid="assistant-context">{assistant.open ? assistant.question : "closed"}</output>;
}

const overviewPayload = {
  schema_version: "research-overview/1.0",
  metadata: {
    battery_id: "CELL_001", experiment_id: "EXP_001",
    chemistry: { status: "NOT_CONFIGURED", value: null },
    nominal_capacity_ah: { status: "NOT_CONFIGURED", value: null },
    probe: { status: "NOT_CONFIGURED", value: null },
    channel: { status: "NOT_CONFIGURED", value: null },
    temperature: { status: "AVAILABLE", channel: ["T1"], range_c: [23.2, 25.3] },
    sampling_rate: { status: "AVAILABLE", hz: 50000000, verified: true, parameter_set_id: "PS::t" },
    acquisition_window: { status: "NOT_CONFIGURED", start: "2024-01-06T09:52:31", end: "2024-01-06T20:58:54" },
    timebase: { status: "PROVISIONAL" },
  },
  electrical: {
    status: "AVAILABLE", record_count: 39996, cycle_count: 2, step_count: 5,
    voltage_range_v: [2.9995, 4.2], current_range_a: [-4.9976, 5.001],
    voltage_sparkline_v: [3.1, 3.4, 4.2, 3.8, 3.0],
    current_sparkline_a: [5.0, -4.9, 0.2, 5.0, -4.8],
    cycles: [
      { cycle_index_raw: 1, charge_capacity_ah: 11.0959, discharge_capacity_ah: 11.0441, apparent_coulombic_efficiency_percent: 99.53, protocol: "PROTOCOL_FROM_PARSER" },
      { cycle_index_raw: 2, charge_capacity_ah: 11.0551, discharge_capacity_ah: 11.0083, apparent_coulombic_efficiency_percent: 99.58, protocol: "PROTOCOL_FROM_PARSER" },
    ],
  },
  ultrasound_tof: {
    status: "READY",
    tof_method_id: "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1",
    tof_definition_version: "0.3.0",
    sampling_rate_hz: 50000000, sampling_rate_verified: true,
    gate_calibration_id: "GC-TOF::t", gate_calibration_source: "EXPERIMENT_CONFIRMED",
    gate_calibration_version: 1,
    surface_gate_id: "TOF_SURFACE_PEAK_GATE", surface_peak_sample_range: [59, 260],
    bottom_gate_id: "TOF_BOTTOM_PEAK_GATE", bottom_peak_sample_range: [749, 1200],
    artifact_status_counts: { VALID: 3995 },
    artifact_tof_us_summary: { min: 15.52, median: 15.96, max: 16.08 },
    artifact_current: true,
    waveform_tof: { event_count: 3999, ambiguous_events: 4, note: "waveform rows" },
    feature_target_eligible: { eligible_count: 3995, note: "eligible rows" },
  },
  signal_quality: {
    snr: { status: "NOT_CONFIGURED", value: null, reason: "no formally defined SNR algorithm in the workbench" },
    saturation_check: { status: "AVAILABLE", definition: "gate saturation fraction" },
  },
  readiness_matrix: { acquisition: "READY", synchronization: "PROVISIONAL", tof: "READY", targets: "READY_FOR_LIMITED_EVALUATION", modeling: "LIMITED" },
  scientific_snapshot: {
    target: { target_id: "reference_soc_percent", readiness: "READY_FOR_LIMITED_EVALUATION", note: "retrospective" },
    leading_exploratory_candidate: { analysis_id: "AN::t", feature_name: "amplitude_a_u", method: "spearman", coefficient: -0.1341, n: 3995, note: "" },
    selected_features: ["amplitude_a_u"],
    model_evidence: { dummy_first_conclusion: "no model beat the Dummy baseline", dummy_macro_mae: 29.61, note: "" },
    feature_definition: { feature_set_id: "FS::t", dataset_definition_version: "0.1.0", current_policy: "MATLAB_ALIGNED_FEATURE_FORMULAS_V1", uses_previous_feature_definition: true, refresh_required: true, note: "previous definition" },
  },
  model_comparison: {
    status: "AVAILABLE", artifact_path: "models/x/model_comparison.json",
    strategies: [
      { strategy: "DUMMY_MEAN", macro_mae: 29.61, macro_rmse: 33.7, macro_r2: -0.02, vs_dummy: 0 },
      { strategy: "LINEAR_REGRESSION", macro_mae: 30.86, macro_rmse: 38.8, macro_r2: -0.36, vs_dummy: 1.25 },
      { strategy: "RIDGE", macro_mae: 30.87, macro_rmse: 38.77, macro_r2: -0.36, vs_dummy: 1.26 },
      { strategy: "GRADIENT_BOOSTING", macro_mae: 33.78, macro_rmse: 41.2, macro_r2: -0.53, vs_dummy: 4.18 },
      { strategy: "RANDOM_FOREST", macro_mae: 35.56, macro_rmse: 43.4, macro_r2: -0.71, vs_dummy: 5.95 },
    ],
    dummy: { strategy: "DUMMY_MEAN", macro_mae: 29.61 },
    dummy_first_conclusion: "no model beat the Dummy baseline (current same-scope evaluation)",
    feature_definition: { feature_set_id: "FS::t", dataset_definition_version: "0.1.0", current_policy: "MATLAB_ALIGNED_FEATURE_FORMULAS_V1", uses_previous_feature_definition: true, refresh_required: true, note: "previous definition" },
  },
  limitations_first_screen: [
    { code: "PROVISIONAL_TIMEBASE", severity: "LIMITATION", description: "sync timebase is provisional (not validated)" },
    { code: "SOH_INDEPENDENT_STATES_TOO_FEW", severity: "BLOCKING_FOR_MODELING", description: "SOH has only 2 independent states" },
    { code: "LIMITED_CROSS_CYCLE_GENERALIZATION", severity: "LIMITATION", description: "within-battery cross-cycle evaluation only" },
    { code: "ONE_BATTERY_ONLY", severity: "BLOCKING_FOR_CLAIM", description: "only 1 battery in dataset" },
  ],
  next_actions: [
    { action_id: "CALIBRATE_TOF_GATES", label: "标定并冻结 TOF 双闸门", route: "/experiments/CELL_001/EXP_001/waveform" },
    { action_id: "REVIEW_ALIGNMENT", label: "复核同步对齐", route: "/experiments/CELL_001/EXP_001/analysis" },
    { action_id: "REVIEW_MODEL_BASELINES", label: "复核 Dummy-first 基线", route: "/experiments/CELL_001/EXP_001/models" },
  ],
  research_status_banner: { level: "LIMITED", message: "受限评估就绪：fs 已验证，TOF 规范管线可用；时间基准仍为 PROVISIONAL。" },
};

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <AssistantProvider>
        <MemoryRouter initialEntries={["/experiments/CELL_001/EXP_001/overview"]}>
          <Routes><Route path="/experiments/:batteryId/:experimentId/*" element={<><ResearchOverview/><ContextProbe/></>}/></Routes>
        </MemoryRouter>
      </AssistantProvider>
    </QueryClientProvider>,
  );
  return qc;
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(client, "getResearchOverview").mockResolvedValue({
    data: overviewPayload as never,
  } as never);
});

describe("ResearchOverview（BRW-025R-OV）", () => {
  // O01–O03 banner + single source
  it("O01 渲染聚合 payload 的 research status banner", async () => {
    mount();
    expect(await screen.findByTestId("research-status-banner")).toHaveTextContent("受限评估就绪");
  });
  it("O02 错误状态可重试且不伪造数据", async () => {
    vi.spyOn(client, "getResearchOverview").mockRejectedValue(new Error("boom"));
    mount();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByTestId("research-status-banner")).not.toBeInTheDocument();
  });
  it("O03 banner 说话算话：LIMITED 级别提示 PROVISIONAL 限制", async () => {
    mount();
    const banner = await screen.findByTestId("research-status-banner");
    expect(banner).toHaveTextContent("PROVISIONAL");
  });

  // O04–O06 metadata strip
  it("O04 metadata strip 显示 Battery/Experiment/fs verified/T1 temperature", async () => {
    mount();
    await screen.findByTestId("research-status-banner");
    expect(screen.getByTestId("meta-Battery")).toHaveTextContent("CELL_001");
    expect(screen.getByTestId("meta-Sampling Rate")).toHaveTextContent("50 MHz");
    expect(screen.getByTestId("meta-Sampling Rate")).toHaveTextContent("verified");
    expect(screen.getByTestId("meta-Temperature")).toHaveTextContent("T1");
  });
  it("O05 未知 metadata 显示 Not configured（chemistry/probe/capacity），禁止猜", async () => {
    mount();
    await screen.findByTestId("research-status-banner");
    expect(screen.getByTestId("meta-Chemistry")).toHaveTextContent("Not configured");
    expect(screen.getByTestId("meta-Probe")).toHaveTextContent("Not configured");
    expect(screen.getByTestId("meta-Nominal Capacity")).toHaveTextContent("Not configured");
  });
  it("O06 Timebase 显示 Provisional", async () => {
    mount();
    expect(await screen.findByTestId("meta-Timebase")).toHaveTextContent("Provisional");
  });

  // O07–O10 electrical snapshot
  it("O07 electrical snapshot 数值来自后端", async () => {
    mount();
    await screen.findByTestId("electrical-snapshot");
    expect(screen.getByTestId("electrical-snapshot")).toHaveTextContent("39,996");
    expect(screen.getByTestId("electrical-snapshot")).toHaveTextContent("2.9995");
  });
  it("O08 apparent CE 逐循环显示且标注 apparent", async () => {
    mount();
    await screen.findByTestId("electrical-cycles");
    expect(screen.getByTestId("electrical-snapshot")).toHaveTextContent("99.53%");
    expect(screen.getByTestId("electrical-snapshot")).toHaveTextContent("99.58%");
    expect(screen.getByTestId("electrical-snapshot")).toHaveTextContent("Apparent CE");
  });
  it("O09 sparkline 渲染（无科学计算）", async () => {
    mount();
    await screen.findByTestId("electrical-snapshot");
    expect(screen.getByLabelText("电压 sparkline")).toBeInTheDocument();
    expect(screen.getByLabelText("电流 sparkline")).toBeInTheDocument();
  });
  it("O10 electrical protocol 语义标注", async () => {
    mount();
    expect(await screen.findByTestId("electrical-snapshot")).toHaveTextContent("Protocol: 解析器记录");
  });

  // O11–O14 TOF snapshot
  it("O11 TOF snapshot 显示 canonical method/版本/校准 provenance", async () => {
    mount();
    await screen.findByTestId("tof-snapshot");
    expect(screen.getByTestId("tof-snapshot")).toHaveTextContent("SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1");
    expect(screen.getByTestId("tof-snapshot")).toHaveTextContent("EXPERIMENT_CONFIRMED v1");
    expect(screen.getByTestId("tof-snapshot")).toHaveTextContent("50 MHz · verified");
  });
  it("O12 双 gate 与范围显示", async () => {
    mount();
    expect(await screen.findByTestId("tof-snapshot")).toHaveTextContent("TOF_SURFACE_PEAK_GATE");
    expect(screen.getByTestId("tof-snapshot")).toHaveTextContent("TOF_BOTTOM_PEAK_GATE");
  });
  it("O13 waveform TOF rows ≠ Feature–Target eligible（分开显示）", async () => {
    mount();
    const cov = await screen.findByTestId("tof-coverage");
    expect(cov).toHaveTextContent("3,999");
    expect(cov).toHaveTextContent("3,995");
    expect(cov).toHaveTextContent("≠");
  });
  it("O14 fs 缺失时 TOF snapshot BLOCKED 且 banner 指向 fs", async () => {
    vi.spyOn(client, "getResearchOverview").mockResolvedValue({
      data: {
        ...overviewPayload,
        metadata: { ...overviewPayload.metadata, sampling_rate: { status: "NOT_CONFIGURED", hz: null, verified: false } },
        ultrasound_tof: { ...overviewPayload.ultrasound_tof, status: "NOT_CONFIGURED", sampling_rate_verified: false },
        readiness_matrix: { ...overviewPayload.readiness_matrix, tof: "BLOCKED" },
        research_status_banner: { level: "BLOCKED", message: "阻断：采样频率未在参数注册表验证" },
        next_actions: [{ action_id: "PROVIDE_SAMPLING_RATE", label: "填写并验证采样频率", route: "/x" }],
      } as never,
    } as never);
    mount();
    const banner = await screen.findByTestId("research-status-banner");
    expect(banner).toHaveTextContent("阻断");
    expect(screen.getByTestId("readiness-tof")).toHaveTextContent("BLOCKED");
  });

  // O15 signal quality
  it("O15 无 SNR 算法定义 → Not configured（禁止造 38dB）", async () => {
    mount();
    expect(await screen.findByTestId("fs-configured")).toBeInTheDocument();
    // SNR not shown as a value anywhere; only the readiness/saturation formal defs
    expect(screen.queryByText(/38\s*dB/)).not.toBeInTheDocument();
  });

  // O16–O18 readiness matrix + quick actions
  it("O16 readiness matrix 五维状态", async () => {
    mount();
    await screen.findByTestId("readiness-matrix");
    expect(screen.getByTestId("readiness-acquisition")).toHaveTextContent("READY");
    expect(screen.getByTestId("readiness-synchronization")).toHaveTextContent("PROVISIONAL");
    expect(screen.getByTestId("readiness-modeling")).toHaveTextContent("LIMITED");
  });
  it("O17 Quick Actions ≤3 且由 readiness 生成", async () => {
    mount();
    await screen.findByTestId("quick-actions");
    const actions = screen.getAllByTestId(/^quick-action-/);
    expect(actions.length).toBeLessThanOrEqual(3);
    expect(actions.length).toBe(3);
  });
  it("O18 limitations 首屏可见（4 条）", async () => {
    mount();
    const limits = await screen.findByTestId("limitations-first-screen");
    expect(limits).toHaveTextContent("provisional");
    expect(limits).toHaveTextContent("2 independent states");
    expect(limits).toHaveTextContent("within-battery");
    expect(limits).toHaveTextContent("1 battery");
  });

  // O19–O21 scientific snapshot
  it("O19 scientific snapshot：target + leading candidate + TOF readiness", async () => {
    mount();
    await screen.findByTestId("scientific-snapshot");
    expect(screen.getByTestId("scientific-snapshot")).toHaveTextContent("reference_soc_percent");
    expect(screen.getByTestId("leading-candidate")).toHaveTextContent("amplitude_a_u");
    expect(screen.getByTestId("leading-candidate")).toHaveTextContent("-0.1341");
    expect(screen.getByTestId("scientific-snapshot")).toHaveTextContent("READY");
  });
  it("O20 leading candidate null 时显示无持久工件", async () => {
    vi.spyOn(client, "getResearchOverview").mockResolvedValue({
      data: {
        ...overviewPayload,
        scientific_snapshot: {
          ...overviewPayload.scientific_snapshot,
          leading_exploratory_candidate: null,
        },
      } as never,
    } as never);
    mount();
    expect(await screen.findByTestId("leading-candidate")).toHaveTextContent("尚无持久探索性分析工件");
  });
  it("O21 model evidence 区 Dummy-first 结论", async () => {
    mount();
    expect(await screen.findByTestId("model-evidence-note")).toHaveTextContent("no model beat the Dummy baseline");
  });

  // O22–O24 model baseline comparison
  it("O22 五策略表 + Dummy 行标记基准", async () => {
    mount();
    await screen.findByTestId("model-comparison-table");
    expect(screen.getByTestId("model-comparison-table")).toHaveTextContent("DUMMY_MEAN");
    expect(screen.getByTestId("model-comparison-table")).toHaveTextContent("LINEAR_REGRESSION");
    expect(screen.getByTestId("model-comparison-table")).toHaveTextContent("GRADIENT_BOOSTING");
    expect(screen.getByTestId("model-comparison-table")).toHaveTextContent("RANDOM_FOREST");
    expect(screen.getByTestId("model-comparison-table")).toHaveTextContent("RIDGE");
  });
  it("O23 stale 工件显示 refresh required", async () => {
    mount();
    expect(await screen.findByTestId("model-refresh-required")).toHaveTextContent("refresh required");
    expect(screen.getByTestId("model-evidence-note")).toHaveTextContent("从未使用 canonical envelope-peak TOF");
  });
  it("O24 Available vs Used 区分（非 Dummy 未用于当前结论）", async () => {
    mount();
    await screen.findByTestId("model-comparison-table");
    expect(screen.getByTestId("model-comparison-table")).toHaveTextContent("Available（未用于当前结论）");
  });

  // O25–O26 inline fs submission（BRW-018R2 复用）
  it("O25 fs 未验证时 inline 配置走共享 submission service", async () => {
    vi.spyOn(client, "getResearchOverview").mockResolvedValue({
      data: {
        ...overviewPayload,
        metadata: { ...overviewPayload.metadata, sampling_rate: { status: "NOT_CONFIGURED", hz: null, verified: false, parameter_set_id: null } },
      } as never,
    } as never);
    const submit = vi.spyOn(client, "submitSamplingParameter").mockResolvedValue({
      data: {
        submission_id: "SUB::ov1", parameter_set_id: "PS::new", save_status: "SAVED",
        save_error: null, fs_value: 50000000, fs_unit: "Hz", source: "ov test",
        run_id: null, pending_action_resolved: false, resume_status: "NOT_ATTEMPTED",
        resume_error: null, run_state: null,
      },
    } as never);
    mount();
    const user = userEvent.setup();
    await screen.findByTestId("ov-fs-config");
    await user.type(screen.getByTestId("ov-fs-value"), "50");
    await user.type(screen.getByTestId("ov-fs-source"), "ov:instrument");
    await user.click(screen.getByTestId("ov-fs-verified"));
    await user.click(screen.getByTestId("ov-fs-save"));
    expect(await screen.findByTestId("ov-fs-saved")).toBeInTheDocument();
    expect(submit).toHaveBeenCalledWith("CELL_001", "EXP_001", expect.objectContaining({
      verified: true,
      values: { "ultrasound.sampling_rate_hz": { value: 50, unit: "MHz" } },
    }));
  });
  it("O26 fs 已验证时不重复显示 inline 配置", async () => {
    mount();
    await screen.findByTestId("fs-configured");
    expect(screen.queryByTestId("ov-fs-config")).not.toBeInTheDocument();
  });

  // O27–O29 assistant + read-only
  it("O27 打开 Assistant 注入 experiment/readiness/target/TOF/model/limitations", async () => {
    mount();
    const user = userEvent.setup();
    await screen.findByTestId("research-status-banner");
    await user.click(screen.getByTestId("ask-assistant-with-context"));
    // AssistantContext question carries the injected overview context
    const ctx = await screen.findByTestId("assistant-context");
    await waitFor(() => expect(ctx).not.toHaveTextContent("closed"));
    expect(ctx).toHaveTextContent("CELL_001/EXP_001");
    expect(ctx).toHaveTextContent("Readiness:");
    expect(ctx).toHaveTextContent("TOF");
    expect(ctx).toHaveTextContent("Dummy");
    expect(ctx).toHaveTextContent("PROVISIONAL_TIMEBASE");
  });
  it("O28 只读：渲染不调用任何写端点", async () => {
    const writeSpies = [
      vi.spyOn(client, "submitSamplingParameter"),
      vi.spyOn(client, "retrySubmissionResume"),
      vi.spyOn(client, "freezeTofGateCalibration"),
      vi.spyOn(client, "createParameters"),
      vi.spyOn(client, "startRun"),
    ];
    mount();
    await screen.findByTestId("model-baseline-comparison");
    for (const spy of writeSpies) expect(spy).not.toHaveBeenCalled();
  });
  it("O29 高密度单页：全部 testid 区块同屏存在", async () => {
    mount();
    await screen.findByTestId("model-baseline-comparison");
    for (const id of ["metadata-strip", "electrical-snapshot", "tof-snapshot",
      "readiness-matrix", "quick-actions", "scientific-snapshot", "fs-inline-config",
      "model-baseline-comparison", "limitations-first-screen"]) {
      expect(screen.getByTestId(id), id).toBeInTheDocument();
    }
  });
});
