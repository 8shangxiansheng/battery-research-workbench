/**
 * Modeling handoff tests: RunsPage user-action payloads (fs {value, unit};
 * CONFIRM_FEATURE_SELECTION echo) and the Models-page modeling launcher
 * (start FULL_PRE_MODEL run, waiting-run gating).
 * @vitest-environment jsdom
 */
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

const clientMock = {
  listRuns: vi.fn(), getRun: vi.fn(), getRunEvents: vi.fn(), listUserActions: vi.fn(),
  submitUserAction: vi.fn(), resumeRun: vi.fn(),
  getResults: vi.fn(), getWorkflowContext: vi.fn(), listSplits: vi.fn(),
  listSplitFolds: vi.fn(), createSplit: vi.fn(), dryRun: vi.fn(), startRun: vi.fn(),
  getArtifact: vi.fn(), createDataset: vi.fn(), listReports: vi.fn(), getLimitations: vi.fn(), createReport: vi.fn(),
  getFeatureCorrelations: vi.fn(), getReport: vi.fn(),
  listCohortDatasets: vi.fn(), runCohortLOBO: vi.fn(), listDatasets: vi.fn(), createCohortDataset: vi.fn(),
  listModelingStrategies: vi.fn(),
};
vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  client: clientMock,
}));

const { RunsPage } = await import("../src/pages/RunsPage");
const { ModelsWorkbench } = await import("../src/pages/redesign/ModelsWorkbench");
const { ReportWorkbench } = await import("../src/pages/redesign/ReportWorkbench");
const { DatasetBuildButtons } = await import("../src/components/workbench/DatasetXYPreview");

function wrap(node: React.ReactNode, route = "/runs", pattern = route) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([{ path: pattern, element: node }], { initialEntries: [route] });
  return render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  clientMock.listCohortDatasets.mockResolvedValue({ data: [], meta: {} });
  clientMock.listDatasets.mockResolvedValue({ data: [], meta: {} });
  clientMock.listModelingStrategies.mockResolvedValue({ data: {
    policy: "FIXED_BASELINE_PROTOCOL",
    strategies: ["DUMMY_MEAN", "LINEAR_REGRESSION", "RIDGE",
      "SUPPORT_VECTOR_REGRESSION", "GAUSSIAN_PROCESS_REGRESSION", "K_NEAREST_NEIGHBORS",
      "RANDOM_FOREST", "GRADIENT_BOOSTING", "ELASTIC_NET", "HUBER_REGRESSION", "MLP_REGRESSOR"
    ].map((strategy) => ({ strategy, fixed_config: {}, stochastic: false, scaled: false })),
  }, meta: {} });
});

describe("RunsPage user actions", () => {
  const fsAction = {
    action_id: "UA::P1", node_id: "PARAMETER_SET", action_type: "MISSING_SAMPLING_RATE",
    message: "请输入采样频率", required_fields: [{ field: "ultrasound.sampling_rate_hz", unit: "Hz", example: 50000000 }],
    options: [], scientific_reason: "r", blocking: true,
  };
  const confirmAction = {
    action_id: "UA::P2", node_id: "FEATURE_ANALYSIS", action_type: "CONFIRM_FEATURE_SELECTION",
    message: "确认特征选择", required_fields: [{ field: "selection_id", value: "SEL::x123" }],
    options: [], scientific_reason: "r", blocking: true,
  };
  function setupRuns(actions: unknown[]) {
    clientMock.listRuns.mockResolvedValue({ data: { runs: [{ run_id: "RUN::r1", status: "WAITING_FOR_USER", experiment_id: "EXP_001" }] }, meta: {} });
    clientMock.getRun.mockResolvedValue({ data: { run_id: "RUN::r1", status: "WAITING_FOR_USER" }, meta: {} });
    clientMock.listUserActions.mockResolvedValue({ data: { run_id: "RUN::r1", user_actions: actions }, meta: {} });
    clientMock.submitUserAction.mockResolvedValue({ data: {}, meta: {} });
    clientMock.resumeRun.mockResolvedValue({ data: {}, meta: {} });
  }

  it("submits sampling rate as {value, unit} without client-side conversion", async () => {
    setupRuns([fsAction]);
    wrap(<RunsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByText("查看"));
    const inp = await screen.findByTestId("fs-input");
    await user.type(inp, "50");
    await user.click(screen.getByTestId("submit-action"));
    await waitFor(() => expect(clientMock.submitUserAction).toHaveBeenCalledWith(
      "RUN::r1", "UA::P1", { "ultrasound.sampling_rate_hz": {
        value: 50, unit: "MHz", source_reference: "实验记录", verification_status: "UNVERIFIED",
      } }));
  });

  it("echoes selection_id prefilled for CONFIRM_FEATURE_SELECTION", async () => {
    setupRuns([confirmAction]);
    wrap(<RunsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByText("查看"));
    const field = await screen.findByTestId("action-field-selection_id");
    expect(field).toHaveValue("SEL::x123");
    await user.click(screen.getByTestId("submit-action"));
    await waitFor(() => expect(clientMock.submitUserAction).toHaveBeenCalledWith(
      "RUN::r1", "UA::P2", { selection_id: "SEL::x123" }));
  });
});

describe("Models-page launcher", () => {
  function setupWf(withSplit: boolean, runs: unknown[] = []) {
    clientMock.getResults.mockResolvedValue({ data: [], meta: {} });
    clientMock.getWorkflowContext.mockResolvedValue({ data: {
      schema_version: "1", battery_id: "CELL_001", experiment_id: "EXP_001", current_step: "DATASET",
      step_statuses: {}, artifact_freshness: {}, typed_actions: [],
      steps: { DATASET: { status: "COMPLETE", committed: { dataset_id: "DS::d1", selected_features: ["SWA"] } },
               ...(withSplit ? { SPLIT: { status: "COMPLETE", committed: { split_id: "SPLIT::s1" } } } : {}) },
    }, meta: {} });
    clientMock.listSplits.mockResolvedValue({ data: { splits: withSplit ? [{ split_id: "SPLIT::s1" }] : [] }, meta: {} });
    clientMock.listRuns.mockResolvedValue({ data: { runs }, meta: {} });
    clientMock.startRun.mockResolvedValue({ data: { run_id: "RUN::fresh" }, meta: {} });
    clientMock.createSplit.mockResolvedValue({ data: { split_id: "SPLIT::s1", status: "CREATED" }, meta: {} });
  }
  const route = "/experiments/CELL_001/EXP_001/models";

  it("starts a FULL_PRE_MODEL run when dataset+split are ready", async () => {
    setupWf(true);
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    const user = userEvent.setup();
    // 默认仅勾选 Dummy 参考基线；再勾选一个 peer 策略后启动
    await user.click(await screen.findByTestId("modeling-strategy-LINEAR_REGRESSION"));
    const btn = await screen.findByTestId("launcher-start-run");
    await waitFor(() => expect(btn).toBeEnabled());
    await user.click(btn);
    await waitFor(() => expect(clientMock.startRun).toHaveBeenCalledWith(expect.objectContaining({
      profile: "FULL_PRE_MODEL", battery_id: "CELL_001", experiment_id: "EXP_001",
      target: "soc_reference_percent", features: { selected_features: ["SWA"] },
      fold_index: 1,
      modeling: expect.objectContaining({
        strategies: ["DUMMY_MEAN", "LINEAR_REGRESSION"],
        random_state: 42,
      }),
      feature_analysis: expect.objectContaining({
        analysis_mode: "TRAIN_ONLY_ML_SAFE", candidate_features: ["SWA"],
      }),
    })));
  });

  it("renders registry strategies as selectable checkboxes with Dummy preselected", async () => {
    setupWf(true);
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    const mlp = await screen.findByTestId("modeling-strategy-MLP_REGRESSOR");
    expect(mlp).not.toBeChecked();
    expect(await screen.findByTestId("modeling-strategy-DUMMY_MEAN")).toBeChecked();
  });

  it("offers in-page split creation when split is missing", async () => {
    setupWf(false);
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("launcher-create-split"));
    await waitFor(() => expect(clientMock.createSplit).toHaveBeenCalledWith({
      battery_id: "CELL_001", experiment_id: "EXP_001", dataset_id: "DS::d1" }));
  });

  it("labels non-current dataset results as historical and excludes them from the current comparison", async () => {
    setupWf(false);
    clientMock.getWorkflowContext.mockResolvedValue({ data: {
      schema_version: "1", battery_id: "CELL_001", experiment_id: "EXP_001", current_step: "DATASET",
      step_statuses: { DATASET: "COMPLETE", MODELS: "BLOCKED" }, artifact_freshness: { models: "STALE" }, typed_actions: [],
      steps: { DATASET: { status: "COMPLETE", committed: { dataset_id: "DS::current", selected_features: ["tof_us"] } } },
    }, meta: {} });
    clientMock.getResults.mockResolvedValue({ data: [{
      result_id: "R::old-dummy", result_type: "MODEL_COMPARISON", strategy: "DUMMY_MEAN",
      value: 30.72, units: "percent", scope: "experiment", dataset_id: "DS::old", split_id: "SPLIT::old",
    }], meta: {} } as never);
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    expect(await screen.findByTestId("historical-model-results")).toHaveTextContent("DS::old");
    expect(screen.getByTestId("historical-model-results")).toHaveTextContent("历史");
    expect(screen.getByText("当前数据集尚无模型评估")).toBeInTheDocument();
    expect(screen.queryByTestId("model-comparison-current")).not.toBeInTheDocument();
  });

  it("marks an old report snapshot and prevents generation without current-dataset model results", async () => {
    setupWf(false);
    clientMock.getWorkflowContext.mockResolvedValue({ data: {
      schema_version: "1", battery_id: "CELL_001", experiment_id: "EXP_001", current_step: "DATASET",
      step_statuses: { DATASET: "COMPLETE", MODELS: "BLOCKED", REPORT: "BLOCKED" },
      artifact_freshness: { report: "STALE", models: "STALE" }, typed_actions: [],
      steps: { DATASET: { status: "COMPLETE", committed: { dataset_id: "DS::current", selected_features: ["tof_us"] } } },
    }, meta: {} });
    clientMock.getResults.mockResolvedValue({ data: [{
      result_id: "R::old-dummy", result_type: "MODEL_COMPARISON", strategy: "DUMMY_MEAN",
      value: 30.72, units: "percent", scope: "experiment", dataset_id: "DS::old", split_id: "SPLIT::old",
    }], meta: {} } as never);
    clientMock.listReports.mockResolvedValue({ data: [{ report_id: "REPORT::old", generated_at: "2025-01-01", scientific_findings: ["Old finding"] }], meta: {} });
    clientMock.getLimitations.mockResolvedValue({ data: { limitations: [] }, meta: {} });
    clientMock.getFeatureCorrelations.mockResolvedValue({ data: { soc: [], temperature: { status: "TEMPERATURE_UNAVAILABLE" }, soh: { status: "NOT_READY_INSUFFICIENT_SOH_STATES" }, soh_cycle_summary: [] }, meta: {} });
    clientMock.getArtifact.mockResolvedValue({ data: { fields: { selected_features: ["tof_us"] } }, meta: {} });
    wrap(<ReportWorkbench />, "/experiments/CELL_001/EXP_001/report", "/experiments/:batteryId/:experimentId/report");
    expect(await screen.findByTestId("report-snapshot-stale")).toHaveTextContent("历史快照");
    expect(screen.getByTestId("report-current-models-missing")).toHaveTextContent("DS::current");
    expect(screen.getByRole("button", { name: /生成报告/ })).toBeDisabled();
  });

  it("blocks starting while a run waits for user confirmation", async () => {
    setupWf(true, [{ run_id: "RUN::w", status: "WAITING_FOR_USER", experiment_id: "EXP_001" }]);
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    expect(await screen.findByTestId("launcher-waiting-run")).toBeInTheDocument();
    expect(screen.getByTestId("launcher-start-run")).toBeDisabled();
  });

  it("keeps cross-battery blocked without an eligible cohort", async () => {
    setupWf(true);
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    expect(await screen.findByTestId("cohort-lobo-blocked")).toHaveTextContent("跨电池泛化仍为阻断状态");
    expect(screen.queryByTestId("run-cohort-lobo")).not.toBeInTheDocument();
  });

  it("runs LOBO only for a verified cohort containing the current experiment", async () => {
    setupWf(true);
    clientMock.listCohortDatasets.mockResolvedValue({ data: [{
      cohort_id: "COHORT::fixture", cohort_dataset_id: "COHORT::version", status: "READY_FOR_BATTERY_SPLIT",
      battery_count: 3, row_count: 12, predictor_columns: ["p2p"], target_column: "reference_soc_percent",
      source_datasets: [{ source_dataset_id: "DS::A", battery_id: "CELL_001", experiment_id: "EXP_001" }],
    }], meta: {} });
    clientMock.runCohortLOBO.mockResolvedValue({ data: {
      evaluation_id: "LOBO::fixture", evaluation_scope: "CROSS_BATTERY_LOBO_LIMITED_EVALUATION",
      battery_count: 3, fold_count: 3,
      macro_by_strategy: { DUMMY_MEAN: { macro_MAE: 22.1, macro_RMSE: 25, aggregation: "MACRO_MEAN_OF_BATTERY_METRICS" } },
      pooled_row_diagnostic_by_strategy: { DUMMY_MEAN: { MAE: 20.4 } },
      battery_results: [{ strategy: "DUMMY_MEAN", battery_id: "CELL_B", fold: "fold2", overall: { MAE: 22.1 }, row_count: 4 }],
      provenance: { cohort_id: "COHORT::fixture", cohort_dataset_id: "COHORT::version", source_datasets: [{ source_dataset_id: "DS::A", battery_id: "CELL_A", experiment_id: "EXP_A" }], harmonization_policy_id: "POLICY::v1", harmonization_method_version: "exact-match/1.0" },
      limitations: [],
    }, meta: {} });
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("run-cohort-lobo"));
    await waitFor(() => expect(clientMock.runCohortLOBO).toHaveBeenCalledWith("COHORT::version"));
    expect(await screen.findByTestId("cohort-lobo-result")).toHaveTextContent("22.1");
    expect(screen.getByTestId("cohort-lobo-result")).toHaveTextContent("CELL_B");
    expect(screen.getByTestId("cohort-lobo-result")).toHaveTextContent("Pooled-row diagnostic");
  });

  it("builds a cohort only after explicit source, feature, policy, and evidence selection", async () => {
    setupWf(true);
    clientMock.listDatasets.mockResolvedValue({ data: [
      { dataset_id: "DS::A", dataset_family: "SOC", dataset_status: "READY_FOR_SPLIT", battery_id: "CELL_A", experiment_id: "EXP_A",
        target_column: "soc_reference_percent", target_method_version: "soc-formula/1.0", soc_label_temporality: "RETROSPECTIVE_REFERENCE",
        predictor_columns: ["p2p"], feature_definitions: [{ name: "p2p", version: "0.1.0", unit: "a.u.", definition_signature: "sig::p2p" }], eligible_rows: 10 },
      { dataset_id: "DS::B", dataset_family: "SOC", dataset_status: "READY_FOR_SPLIT", battery_id: "CELL_B", experiment_id: "EXP_B",
        target_column: "soc_reference_percent", target_method_version: "soc-formula/1.0", soc_label_temporality: "RETROSPECTIVE_REFERENCE",
        predictor_columns: ["p2p"], feature_definitions: [{ name: "p2p", version: "0.1.0", unit: "a.u.", definition_signature: "sig::p2p" }], eligible_rows: 12 },
    ], meta: {} });
    clientMock.createCohortDataset.mockResolvedValue({ data: {
      cohort_id: "COHORT::CELL_A-CELL_B", cohort_dataset_id: "COHORT::version", status: "READY_FOR_BATTERY_SPLIT",
      battery_count: 2, row_count: 22, predictor_columns: ["p2p"], target_column: "reference_soc_percent",
      source_datasets: [],
    }, meta: {} });
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("cohort-source-CELL_A"));
    await user.click(screen.getByTestId("cohort-source-CELL_B"));
    await user.click(screen.getByTestId("cohort-feature-p2p"));
    expect(screen.getByTestId("create-cohort")).toBeDisabled();
    await user.click(screen.getByText("队列策略与证据引用（必填）"));
    await user.type(screen.getByLabelText("Harmonization policy ID"), "POLICY::verified");
    await user.type(screen.getByLabelText(/Evidence references/), "SOP::review");
    await waitFor(() => expect(screen.getByTestId("create-cohort")).toBeEnabled());
    await user.click(screen.getByTestId("create-cohort"));
    await waitFor(() => expect(clientMock.createCohortDataset).toHaveBeenCalledWith(expect.objectContaining({
      target_mapping: expect.objectContaining({ method_version: "soc-formula/1.0", unit: "percent" }),
      feature_mappings: [{ canonical_feature_id: "p2p", source_feature_ids: { "DS::A": "p2p", "DS::B": "p2p" }, method_version: "0.1.0" }],
      harmonization_policy_id: "POLICY::verified", evidence_refs: ["SOP::review"],
    })));
    expect(await screen.findByTestId("cohort-created")).toHaveTextContent("2 块电池");
  });
});

describe("Dataset materialization handoff", () => {
  it("creates the dataset spec and immediately launches BUILD_DATASET", async () => {
    clientMock.createDataset.mockResolvedValue({
      data: { dataset_id: "DS::draft", materialization_status: "SPEC_PENDING_RUN" }, meta: {},
    });
    clientMock.startRun.mockResolvedValue({ data: { run_id: "RUN::dataset", status: "SUCCEEDED" }, meta: {} });
    const onBuilt = vi.fn();
    wrap(<DatasetBuildButtons batteryId="CELL_001" experimentId="EXP_001"
      targetId="reference_soc_percent" features={["SWA"]} mode="TRAIN_ONLY_ML_SAFE"
      target={undefined} summary={null} onBuilt={onBuilt} />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("build-mlsafe-btn"));
    await user.click(await screen.findByTestId("confirm-build-dataset"));
    await waitFor(() => expect(clientMock.startRun).toHaveBeenCalledWith({
      profile: "BUILD_DATASET", battery_id: "CELL_001", experiment_id: "EXP_001",
      target: "soc_reference_percent", features: { selected_features: ["SWA"] },
    }));
    expect(onBuilt).toHaveBeenCalledWith("mlsafe");
  });
});
