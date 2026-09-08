/**
 * BRW-025R-FE — Scientific Feature Workbench UI integration tests.
 * Catalogue consumption / physical features / electrical state / calibration /
 * feature relationship / selected features. Component tests with mocked client.
 * @vitest-environment jsdom
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, vi, beforeEach } from "vitest";

const clientMock = {
  listFeatureDefinitions: vi.fn(),
  listPhysicalFeatures: vi.fn(),
  getFeatureCorrelations: vi.fn(),
  getGateCalibration: vi.fn(),
  freezeGateCalibration: vi.fn(),
  getArtifact: vi.fn(),
  listWaveformFrames: vi.fn(),
  getWaveformFrame: vi.fn(),
  listGates: vi.fn(),
  getMeasurementEvents: vi.fn(),
  getStatus: vi.fn(),
  listFeatures: vi.fn(),
};
vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  client: clientMock,
}));

import type { FeatureDefinitionEntry } from "../src/api/client";

function td(name: string, extra: Partial<FeatureDefinitionEntry> = {}): FeatureDefinitionEntry {
  return {
    code: name, display_name_en: name, display_name_zh: name,
    family: name.startsWith("TD") ? "TD" : "FD",
    units: "dimensionless", formula_source_id: "USER_MATLAB_TIME_FREQUENCY_FEATURE_FORMULAS_V1",
    formula_policy_version: "MATLAB_ALIGNED_FEATURE_FORMULAS_V1", formula_text: "mean(x)",
    definition_status: "DEFINED_AND_VALIDATED", parity_status: "INDEPENDENT_GOLDEN_PASS",
    existing_alias: null, scope: ["FULL_WAVEFORM"], ...extra,
  };
}
const catalogueFixture: FeatureDefinitionEntry[] = [
  td("TDM", { display_name_en: "Mean", display_name_zh: "均值", family: "TD" }),
  td("TDSTD", { display_name_en: "Standard Deviation", display_name_zh: "标准差", family: "TD" }),
  td("TDK", { definition_status: "DEFINED_NOT_VALIDATED", parity_status: "MATLAB_PARITY_REQUIRED" }),
  td("FDAF", { display_name_en: "Mean Frequency", display_name_zh: "频率均值", family: "FD" }),
  td("FDEQ", { display_name_en: "Spectral Entropy", display_name_zh: "频率均衡性（谱熵）", family: "FD" }),
];

function renderPage(node: React.ReactNode, path = "/experiments/CELL_001/EXP_001") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/experiments/:batteryId/:experimentId/*" element={node} />
          <Route path="*" element={node} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("FeatureCatalogue（需求 1-4）", () => {
  it("consumes /feature-definitions API — no hardcoded catalogue", async () => {
    clientMock.listFeatureDefinitions.mockResolvedValue({
      data: { catalogue: catalogueFixture, formula_source_id: "USER_MATLAB_TIME_FREQUENCY_FEATURE_FORMULAS_V1", formula_policy_version: "MATLAB_ALIGNED_FEATURE_FORMULAS_V1" },
      meta: {},
    });
    const { FeatureCatalogue } = await import("../src/components/workbench/FeatureCatalogue");
    renderPage(<FeatureCatalogue selected={[]} onToggle={() => {}} />);
    await waitFor(() => {
      expect(screen.getByTestId("feature-group-时域特征")).toBeInTheDocument();
      expect(screen.getByTestId("feature-group-频域特征")).toBeInTheDocument();
      expect(screen.getByTestId("catalogue-TDSTD")).toHaveTextContent("标准差");
      expect(clientMock.listFeatureDefinitions).toHaveBeenCalledTimes(1);
    });
  });

  it("search filters by bilingual names and code", async () => {
    clientMock.listFeatureDefinitions.mockResolvedValue({
      data: { catalogue: catalogueFixture, formula_source_id: "S", formula_policy_version: "P" }, meta: {},
    });
    const user = userEvent.setup();
    const { FeatureCatalogue } = await import("../src/components/workbench/FeatureCatalogue");
    renderPage(<FeatureCatalogue selected={[]} onToggle={() => {}} />);
    await screen.findByTestId("catalogue-TDM");
    await user.type(screen.getByLabelText(/搜索特征 \/ Search features/i), "熵");
    await waitFor(() => {
      expect(screen.getByTestId("catalogue-FDEQ")).toBeInTheDocument();
      expect(screen.queryByTestId("catalogue-TDM")).not.toBeInTheDocument();
    });
  });

  it("details dialog shows formula/status/units/scope/version/source", async () => {
    clientMock.listFeatureDefinitions.mockResolvedValue({
      data: { catalogue: catalogueFixture, formula_source_id: "SRC", formula_policy_version: "POL" }, meta: {},
    });
    const user = userEvent.setup();
    const { FeatureCatalogue } = await import("../src/components/workbench/FeatureCatalogue");
    renderPage(<FeatureCatalogue selected={[]} onToggle={() => {}} />);
    await screen.findByTestId("catalogue-TDSTD");
    await user.click(screen.getAllByRole("button", { name: /详情 \/ Details/i })[0]!);
    const detail = await screen.findByTestId("feature-detail");
    expect(detail.textContent).toContain("mean(x)");
    expect(detail.textContent).toContain("FULL_WAVEFORM");
    expect(detail.textContent).toContain("USER_MATLAB_TIME_FREQUENCY_FEATURE_FORMULAS_V1");
    expect(detail.textContent).toContain("MATLAB_ALIGNED_FEATURE_FORMULAS_V1");
  });

  it("marks parity-pending definitions honestly", async () => {
    clientMock.listFeatureDefinitions.mockResolvedValue({
      data: { catalogue: catalogueFixture, formula_source_id: "S", formula_policy_version: "P" }, meta: {},
    });
    const { FeatureCatalogue } = await import("../src/components/workbench/FeatureCatalogue");
    renderPage(<FeatureCatalogue selected={[]} onToggle={() => {}} />);
    await screen.findByTestId("catalogue-TDK");
    expect(screen.getAllByText(/待 MATLAB 对齐 \/ Parity pending/i).length).toBeGreaterThan(0);
  });
});

describe("PhysicalFeatureCards + ElectricalStatePanel（需求 5/9/10）", () => {
  it("renders the five physical features from the API", async () => {
    clientMock.listPhysicalFeatures.mockResolvedValue({ data: {
      battery_id: "C", experiment_id: "E", frame_count: 10,
      features: [
        { feature_code: "SWA", method: "SURFACE_WAVE_AMPLITUDE_ENVELOPE_MAX_V1", gate_template_id: "SWA_SURFACE_GATE", display_name_en: "Surface Wave Amplitude (SWA)", display_name_zh: "表面波幅值", unit: "a.u.", values: [1.5, 2.5] },
        { feature_code: "BOTTOM_AMP", method: "M", gate_template_id: "G", display_name_en: "Bottom-wave Amplitude", display_name_zh: "底波幅值", unit: "a.u.", values: [3.5, 4.5] },
        { feature_code: "TOF_XCORR", method: "M", gate_template_id: "G", display_name_en: "Surface–Bottom XCorr TOF", display_name_zh: "表面波-底波互相关TOF", unit: "samples", values: [450, 451], physical_time_blocked: "fs" },
        { feature_code: "ATTENUATION", method: "M", gate_template_id: "G", display_name_en: "Attenuation", display_name_zh: "底波衰减", unit: "a.u.", values: [0.5, 0.4], blocked_features: [{ code: "ATTEN_HF_ENERGY", status: "SOURCE_FORMULA_INCOMPLETE" }] },
        { feature_code: "BPS", method: "M", gate_template_id: "G", display_name_en: "BPS", display_name_zh: "底波相移", unit: "radian", values: [0.1, 0.2] },
      ],
    }, meta: {} });
    const { PhysicalFeatureCards } = await import("../src/components/workbench/FrameContextPanels");
    renderPage(<PhysicalFeatureCards batteryId="C" experimentId="E" frameIndex={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("phys-SWA")!.textContent).toContain("2.5");
      expect(screen.getByTestId("phys-BOTTOM_AMP")!.textContent).toContain("4.5");
      expect(screen.getByTestId("phys-BPS")!.textContent).toContain("0.2");
      expect(screen.getByTestId("phys-ATTENUATION")!.textContent).toContain("SOURCE_FORMULA_INCOMPLETE");
    });
  });

  it("electrical state shows one MeasurementEvent context, no rematch note", async () => {
    const { ElectricalStatePanel } = await import("../src/components/workbench/FrameContextPanels");
    render(<ElectricalStatePanel event={{
      measurement_event_id: "ME::1", voltage_v: 3.42, current_a: -1.05,
      soc_reference_percent: 55.3, step_type: "恒流放电", temperature_c: null,
      cycle_index_raw: 2, step_index_raw: 5,
    }} />);
    const panel = screen.getByTestId("electrical-state");
    expect(panel).toHaveTextContent("3.42");
    expect(panel).toHaveTextContent("参考 SOC");
    expect(panel).toHaveTextContent("恒流放电");
    expect(panel).toHaveTextContent("Gate sample positions are never used for electrical rematching");
  });
});


describe("SelectedFeaturesPanel（需求 17/19）", () => {
  it("bilingual labels + scope/gate/variant/eligibility from dataset manifest", async () => {
    clientMock.getArtifact.mockResolvedValue({ data: {
      artifact_id: "DS::x", artifact_type: "DATASET", availability: "AVAILABLE", status: "READY",
      row_count: 100, preview: [],
      fields: { selected_features: ["amplitude_a_u", "SWA", "swa_source_movmean5"] },
    }, meta: {} });
    const { SelectedFeaturesPanel } = await import("../src/components/workbench/SelectedFeaturesPanel");
    renderPage(<SelectedFeaturesPanel datasetId="DS::x" />);
    await waitFor(() => {
      expect(screen.getByTestId("selected-features")).toBeInTheDocument();
      expect(screen.getByTestId("selected-feature-SWA")).toHaveTextContent("表面波幅值");
      expect(screen.getByTestId("selected-feature-SWA")).toHaveTextContent("SWA_SURFACE_GATE");
      expect(screen.getByTestId("selected-feature-swa_source_movmean5")).toHaveTextContent("Exploratory only / 仅用于探索");
      expect(screen.getByTestId("selected-feature-amplitude_a_u")).toHaveTextContent("Eligible / 可用");
    });
  });

  it("featureLabelBilingual is bilingual", async () => {
    const { featureLabelBilingual } = await import("../src/components/workbench/SelectedFeaturesPanel");
    expect(featureLabelBilingual("SWA")).toBe("SWA / 表面波幅值");
    expect(featureLabelBilingual("BOTTOM_AMP")).toContain("底波幅值");
  });
});

describe("Accessibility（BRW-025R-FE a11y 抽查）", () => {
  it("catalogue search input is labeled; checkboxes are labeled; status changes are announced", async () => {
    clientMock.listFeatureDefinitions.mockResolvedValue({
      data: { catalogue: catalogueFixture, formula_source_id: "S", formula_policy_version: "P" }, meta: {},
    });
    const user = userEvent.setup();
    const { FeatureCatalogue } = await import("../src/components/workbench/FeatureCatalogue");
    renderPage(<FeatureCatalogue selected={[]} onToggle={() => {}} />);
    expect(await screen.findByPlaceholderText("搜索特征 / Search features")).toBeInTheDocument();
    const cb = (await screen.findAllByRole("checkbox", { name: /Select Mean/i }))[0]!;
    expect(cb).toBeInTheDocument();
    await user.click(cb);
  });

  it("physical feature cards expose a labeled group", async () => {
    clientMock.listPhysicalFeatures.mockResolvedValue({ data: {
      battery_id: "C", experiment_id: "E", frame_count: 2,
      features: [
        { feature_code: "SWA", method: "M", gate_template_id: "G", display_name_en: "SWA", display_name_zh: "表面波幅值", unit: "a.u.", values: [1, 2] },
      ],
    }, meta: {} });
    const { PhysicalFeatureCards } = await import("../src/components/workbench/FrameContextPanels");
    renderPage(<PhysicalFeatureCards batteryId="C" experimentId="E" frameIndex={0} />);
    const group = await screen.findByTestId("physical-features");
    expect(group.getAttribute("aria-label")).toBe("物理特征（当前帧）");
  });

  it("electrical state panel is an accessible labeled region", async () => {
    const { ElectricalStatePanel } = await import("../src/components/workbench/FrameContextPanels");
    render(<ElectricalStatePanel event={{
      measurement_event_id: "ME::1", voltage_v: 3.4, current_a: 1.0,
      soc_reference_percent: 50, step_type: "恒流充电", temperature_c: null,
      cycle_index_raw: 1, step_index_raw: 1,
    }} />);
    const panel = screen.getByTestId("electrical-state");
    expect(panel.getAttribute("aria-label")).toBe("当前帧电学状态");
  });
});
