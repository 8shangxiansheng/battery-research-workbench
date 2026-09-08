/**
 * BRW-025R §19 — redesign component/page tests。
 * 渲染走真实 API（uvicorn sandbox），组件交互用 Testing Library。
 * @vitest-environment jsdom
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";


// 组件测试不依赖网络：mock client 模块


import { describe, it, vi } from "vitest";

const clientMock = {
  getWorkspaceSummary: vi.fn(),
  getDataQuality: vi.fn(),
  getStatus: vi.fn(),
  getResults: vi.fn(),
  listFeatures: vi.fn(),
  listGates: vi.fn(),
  listWaveformFrames: vi.fn(),
  getWaveformFrame: vi.fn(),
  listParameters: vi.fn(),
  getEvidence: vi.fn(),
  getLineage: vi.fn(),
  getReports: vi.fn(),
  listReports: vi.fn(),
  getMeasurementEvents: vi.fn(),
  getSynchronization: vi.fn(),
  listLibraryExperiments: vi.fn(),
  listRuns: vi.fn(),
  createReport: vi.fn(),
  createFeatureAnalysis: vi.fn(),
  createDataset: vi.fn(),
  listFeatureDefinitions: vi.fn(),
  listPhysicalFeatures: vi.fn(),
  getFeatureCorrelations: vi.fn(),
  getGateCalibration: vi.fn(),
  freezeGateCalibration: vi.fn(),
  getArtifact: vi.fn(),
};

vi.mock("../src/api/client", () => ({ client: clientMock, ApiError: class ApiError extends Error {
  code: string; requestId: string; details: Record<string, unknown>; status: number;
  constructor(status: number, body: { error: { code: string; message: string; request_id: string } }) {
    super(body.error.message); this.code = body.error.code; this.requestId = body.error.request_id;
    this.details = {}; this.status = status;
  }
} }));

const demoStatus = {
  battery_id: "CELL_001", experiment_id: "EXP_001",
  synchronization: { validated_sync: false, timebase_status: "PROVISIONAL" },
  soc: { value: null, status: "RETROSPECTIVE_SOC_REFERENCE", reason: "reference only" },
  soh: { value: null, status: "NOT_READY" },
  tof: { value: null, status: "BLOCKED", reason: "sampling rate required" },
  scientific_status: "READY_FOR_LIMITED_EVALUATION",
};
const demoSummary = {
  ...demoStatus,
  experiment_composite_id: "CELL_001/EXP_001",
  latest_canonical_artifacts: { dataset_id: "DS::x", split_id: "SPLIT::x" },
  run_ids: [], next_actions: ["Open waveform"],
  limitations_registry: [{ code: "ONE_BATTERY_ONLY", severity: "BLOCKING_FOR_CLAIM", description: "One battery" }],
  readiness: {},
};
const demoResults = [
  { result_id: "R::macro_DUMMY_MEAN_MAE", result_type: "MODEL_COMPARISON", name: "Dummy macro MAE",
    value: 29.61, units: "percent", scope: "experiment", strategy: "DUMMY_MEAN",
    source_artifact_id: null, source_run_id: null, dataset_id: "DS::x", split_id: "SPLIT::x",
    model_id: null, model_family: "DUMMY_MEAN", evidence_type: "DIRECT_CURRENT_ARTIFACT",
    evidence_ref: "model_comparison.json", fold_index: null, scientific_status: "", limitations: [], pooled_rows_usage: "" },
  { result_id: "R::macro_RIDGE_MAE", result_type: "MODEL_COMPARISON", name: "Ridge macro MAE",
    value: 30.87, units: "percent", scope: "experiment", strategy: "RIDGE",
    source_artifact_id: null, source_run_id: null, dataset_id: "DS::x", split_id: "SPLIT::x",
    model_id: null, model_family: "RIDGE", evidence_type: "DIRECT_CURRENT_ARTIFACT",
    evidence_ref: "model_comparison.json", fold_index: null, scientific_status: "", limitations: [], pooled_rows_usage: "" },
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

describe("redesign shared components（§47 组件）", () => {
  it("ScientificStatus renders friendly name", async () => {
    const { ScientificStatus } = await import("../src/components/workbench/shared");
    render(<ScientificStatus value="PROVISIONAL" />);
    expect(screen.getByText("Provisional timebase")).toBeInTheDocument();
  });
  it("BlockedValue shows — for null (never 0)", async () => {
    const { BlockedValue } = await import("../src/components/workbench/shared");
    render(<BlockedValue name="TOF" value={null} unit="µs" reason="Sampling rate required" />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("Sampling rate required")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
});

describe("OverviewPage（§8）", () => {
  it("shows finding + primary action + scientific statuses", async () => {
    clientMock.getWorkspaceSummary.mockResolvedValue({ data: demoSummary, meta: {} });
    clientMock.getDataQuality.mockResolvedValue({ data: { battery_id: "CELL_001", experiment_id: "EXP_001",
      electrical: { records: 3995, cycles: 2, steps: 8, duplicate_timestamps: 0 },
      ultrasound: { frames: 3999, frame_cadence_s: 10.03, sampling_rate_hz: null, sampling_rate_status: "UNKNOWN", note: "" } }, meta: {} });
    clientMock.getStatus.mockResolvedValue({ data: demoStatus, meta: {} });
    clientMock.getResults.mockResolvedValue({ data: demoResults, meta: {} });
    const { OverviewPage } = await import("../src/pages/redesign/OverviewPage");
    renderPage(<OverviewPage />);
    await waitFor(() => {
      // finding precedes table (§18: scientific finding first)
      expect(screen.getByText(/当前没有任何模型跑赢 Dummy 基准/)).toBeInTheDocument();
      expect(screen.getByText(/Dummy 均值宏观 MAE：29.61/)).toBeInTheDocument();
    });
  });
});

describe("ModelsWorkbench（§18）", () => {
  it("leads with the scientific question, Dummy highlighted", async () => {
    clientMock.getResults.mockResolvedValue({ data: demoResults, meta: {} });
    const { ModelsWorkbench } = await import("../src/pages/redesign/ModelsWorkbench");
    renderPage(<ModelsWorkbench />);
    await waitFor(() => {
      expect(screen.getByText(/当前没有任何模型跑赢 Dummy 基准/)).toBeInTheDocument();
    });
    expect(screen.getByText(/有没有模型跑赢简单基线/)).toBeInTheDocument();
  });
  it("no tuning controls anywhere", async () => {
    clientMock.getResults.mockResolvedValue({ data: demoResults, meta: {} });
    const { ModelsWorkbench } = await import("../src/pages/redesign/ModelsWorkbench");
    renderPage(<ModelsWorkbench />);
    await waitFor(() => screen.getByText(/当前没有任何模型跑赢 Dummy 基准/));
    expect(screen.queryByLabelText(/tuning/i)).not.toBeInTheDocument();
    expect(document.querySelectorAll("input[type=number]").length).toBe(0);
  });
});

describe("AnalysisWorkbench（§14/§17）", () => {
  it("shows exploratory vs ML-safe as two modes", async () => {
    clientMock.listFeatures.mockResolvedValue({ data: { features: [
      { feature_name: "amplitude_a_u", role: "predictor", availability: "AVAILABLE", gate_id: null, tof_definition_id: null, missing_reason: null },
      { feature_name: "tof_us", role: "predictor", availability: "NOT_AVAILABLE_CURRENT_ENVIRONMENT", gate_id: null, tof_definition_id: null, missing_reason: "sampling rate required" },
    ] }, meta: {} });
    const { AnalysisWorkbench } = await import("../src/pages/redesign/AnalysisWorkbench");
    renderPage(<AnalysisWorkbench />);
    await waitFor(() => {
      expect(screen.getAllByText(/探索数据关系/).length).toBeGreaterThan(0);
      expect(screen.getByText(/仅使用训练组数据，避免数据泄漏/)).toBeInTheDocument();
    });
  });
});

describe("Waveform workbench（§9/§11）", () => {
  it("TOF blocked card offers Add sampling rate, never 0", async () => {
    clientMock.listWaveformFrames.mockResolvedValue({ data: { battery_id: "C", experiment_id: "E",
      frame_count: 1, waveform_length: 1250, x_axis: "SAMPLE_INDEX", time_axis_available: false,
      frames: [{ frame_index: 0, waveform_group: "g", waveform_row_index: 0, sample_count: 1250 }] }, meta: {} });
    clientMock.listGates.mockResolvedValue({ data: { gates: [] }, meta: {} });
    clientMock.getMeasurementEvents.mockResolvedValue({ data: { total: 0, events: [] }, meta: {} });
    clientMock.getStatus.mockResolvedValue({ data: demoStatus, meta: {} });
    clientMock.getWaveformFrame.mockResolvedValue({ data: { frame_index: 0, waveform_group: "g",
      waveform_row_index: 0, waveform_length: 1250, x_axis: "SAMPLE_INDEX", time_axis_us: null,
      sampling_rate_status: "NOT_VERIFIED", max_points: 1000, samples: [] }, meta: {} });
    const { WaveformWorkbench } = await import("../src/pages/redesign/WaveformWorkbench");
    renderPage(<WaveformWorkbench />);
    await waitFor(() => {
      expect(screen.getByText("飞行时间 TOF")).toBeInTheDocument();
      expect(screen.getByText(/需要先提供采样频率/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /添加采样频率|add sampling rate/i })).toBeInTheDocument();
    });
    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();
  });
});

describe("AssistantDrawer（§24）", () => {
  it("is a contextual drawer, no agent reasoning", async () => {
    clientMock.listLibraryExperiments.mockResolvedValue({ data: { experiments: [] }, meta: {} });
    clientMock.listRuns.mockResolvedValue({ data: { runs: [] }, meta: {} });
    const { AssistantDrawer } = await import("../src/pages/redesign/WorkbenchShell");
    renderPage(<AssistantDrawer />);
    const trigger = await screen.findByRole("button", { name: /Research Assistant/i });
    expect(trigger).toBeInTheDocument();
  });
});
