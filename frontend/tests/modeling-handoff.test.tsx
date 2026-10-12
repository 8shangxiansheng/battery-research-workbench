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
  listSplitFolds: vi.fn(), listMaterializedAnalyses: vi.fn(), createSplit: vi.fn(), dryRun: vi.fn(), startRun: vi.fn(),
  getArtifact: vi.fn(), createDataset: vi.fn(), listReports: vi.fn(), getLimitations: vi.fn(), createReport: vi.fn(),
  getFeatureCorrelations: vi.fn(), getReport: vi.fn(), listTargets: vi.fn(),
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
  clientMock.listTargets.mockResolvedValue({ data: { targets: [] }, meta: {} });
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
    options: [],
    scientific_reason: "TRAIN_ONLY_ML_SAFE target=soc_reference_percent, split_id=SPLIT::s1, fold=1; selected feature locators: tof_us, amplitude_a_u.",
    blocking: true,
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
    const runList = await screen.findByTestId("run-list-disclosure");
    expect(runList).toHaveAttribute("open");
    await user.click(await screen.findByText("查看"));
    expect(runList).not.toHaveAttribute("open");
    expect(await screen.findByText("查看运行技术详情（原始 JSON）")).toBeInTheDocument();
    expect(await screen.findByText(/TRAIN_ONLY_ML_SAFE target=soc_reference_percent/)).toBeInTheDocument();
    expect(screen.getByText(/selected feature locators: tof_us, amplitude_a_u/)).toBeInTheDocument();
    expect(await screen.findByText("SEL::x123")).toBeInTheDocument();
    expect(screen.queryByTestId("action-field-selection_id")).not.toBeInTheDocument();
    expect(screen.getByTestId("submit-action")).toHaveTextContent("确认上述特征并继续");
    expect(screen.queryByTestId("resume-run")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("submit-action"));
    await waitFor(() => expect(clientMock.submitUserAction).toHaveBeenCalledWith(
      "RUN::r1", "UA::P2", { selection_id: "SEL::x123" }));
  });

  it("offers parser-only recovery for invalid source manifests in experiment context", async () => {
    setupRuns([]);
    clientMock.getWorkflowContext.mockResolvedValue({ data: {
      schema_version: "1", battery_id: "CELL_001", experiment_id: "EXP_001", current_step: "TARGET",
      step_statuses: {}, artifact_freshness: {}, typed_actions: [], steps: {},
      recommended_next_action: null, pending_action: null, scientific_context: {}, assistant_context: null,
      meta: {
        read_only: true, no_recomputation: true,
        source_integrity_status: "INTEGRITY_BLOCKED", invalid_modalities: ["electrical"],
      },
    }, meta: {} });
    clientMock.startRun.mockResolvedValue({ data: { run_id: "RUN::reparse", status: "SUCCEEDED" }, meta: {} });
    wrap(
      <RunsPage />,
      "/experiments/CELL_001/EXP_001/advanced/runs",
      "/experiments/:batteryId/:experimentId/advanced/runs",
    );

    expect(await screen.findByTestId("source-integrity-recovery")).toHaveTextContent("不运行同步、特征或模型步骤");
    await userEvent.setup().click(screen.getByTestId("reparse-source-assets"));

    await waitFor(() => expect(clientMock.startRun).toHaveBeenCalledWith({
      profile: "INGEST_TO_MEASUREMENT_EVENTS",
      battery_id: "CELL_001",
      experiment_id: "EXP_001",
      stages: ["ELECTRICAL_CANONICAL"],
    }));
  });

  it("offers explicit TimeAnchor and alignment-chain rebuild for stale timebase provenance", async () => {
    setupRuns([]);
    clientMock.getWorkflowContext.mockResolvedValue({ data: {
      schema_version: "1", battery_id: "CELL_001", experiment_id: "EXP_001", current_step: "TARGET",
      step_statuses: { ALIGNMENT: "BLOCKED" }, artifact_freshness: {}, typed_actions: [],
      steps: { ALIGNMENT: { status: "BLOCKED", blocking: {
        required_action: "REBUILD_TIME_ANCHORS_AND_DOWNSTREAM_ALIGNMENT",
        blocking_message: "同步链过期", scientific_reason: "TIME_ANCHOR_SOURCE_STALE",
      } } },
      recommended_next_action: null, pending_action: null, scientific_context: {}, assistant_context: null,
      meta: { read_only: true },
    }, meta: {} });
    clientMock.startRun.mockResolvedValue({ data: { run_id: "RUN::timebase-rebuild", status: "RUNNING" }, meta: {} });
    wrap(
      <RunsPage />,
      "/experiments/CELL_001/EXP_001/advanced/runs",
      "/experiments/:batteryId/:experimentId/advanced/runs",
    );

    const recovery = await screen.findByTestId("timebase-chain-recovery");
    expect(recovery).toHaveTextContent("不会将同步标记为已验证");
    await userEvent.setup().click(screen.getByTestId("rebuild-timebase-chain"));

    await waitFor(() => expect(clientMock.startRun).toHaveBeenCalledWith({
      profile: "INGEST_TO_MEASUREMENT_EVENTS",
      battery_id: "CELL_001",
      experiment_id: "EXP_001",
    }));
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
    clientMock.listSplitFolds.mockResolvedValue({ data: { split_id: "SPLIT::s1", strategy: "LEAVE_ONE_GROUP_OUT", folds: [
      { fold: "fold1", train_rows: 20, held_out_rows: 10 },
      { fold: "fold2", train_rows: 10, held_out_rows: 20 },
    ] }, meta: {} });
    clientMock.listMaterializedAnalyses.mockResolvedValue({ data: { analyses: [] }, meta: {} });
    clientMock.listRuns.mockResolvedValue({ data: { runs }, meta: {} });
    clientMock.startRun.mockResolvedValue({ data: {
      run_id: "RUN::fresh", status: "SUCCEEDED",
      final_artifacts: [{ artifact_type: "SPLIT", artifact_id: "SPLIT::fresh" }],
    }, meta: {} });
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
      split_id: "SPLIT::s1",
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

  it("allows a TRAIN-only proposal for a selected fold and warns until every fold is confirmed", async () => {
    setupWf(true);
    clientMock.startRun.mockResolvedValue({ data: { run_id: "RUN::fold2", status: "WAITING_FOR_USER" }, meta: {} });
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    const user = userEvent.setup();

    expect(await screen.findByTestId("model-fold-coverage-status")).toHaveTextContent("只作部分折诊断");
    await user.click(await screen.findByTestId("model-fold-fold2"));
    await user.click(await screen.findByTestId("launcher-start-run"));

    await waitFor(() => expect(clientMock.startRun).toHaveBeenCalledWith(expect.objectContaining({
      split_id: "SPLIT::s1",
      fold_index: 2,
      feature_analysis: expect.objectContaining({ split_id: "SPLIT::s1", fold_index: 2 }),
    })));
  });

  it("does not count a confirmed analysis from another candidate or policy as fold coverage", async () => {
    setupWf(true);
    clientMock.listMaterializedAnalyses.mockResolvedValue({ data: { analyses: [
      { analysis_id: "AN::other-policy", analysis_mode: "TRAIN_ONLY_ML_SAFE", target: "soc_reference_percent",
        split_id: "SPLIT::s1", fold_index: 1, dataset_id: "DS::d1", candidate_features: ["SWA"],
        methods: ["descriptive", "spearman"], selection_policy: { min_abs_spearman: 0.5, max_missing_fraction: 0.05 },
        selected_features: ["SWA"], selection_basis: "TRAIN_ONLY_RULE_BASED", selection_status: "CONFIRMED",
        status: "AVAILABLE", availability: "AVAILABLE" },
      { analysis_id: "AN::other-candidate", analysis_mode: "TRAIN_ONLY_ML_SAFE", target: "soc_reference_percent",
        split_id: "SPLIT::s1", fold_index: 2, dataset_id: "DS::d1", candidate_features: ["SWA", "OTHER"],
        methods: ["descriptive", "spearman"], selection_policy: { min_abs_spearman: 0.15, max_missing_fraction: 0.05 },
        selected_features: ["SWA"], selection_basis: "TRAIN_ONLY_RULE_BASED", selection_status: "CONFIRMED",
        status: "AVAILABLE", availability: "AVAILABLE" },
    ] }, meta: {} });
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");

    expect(await screen.findByTestId("model-fold-fold1")).toHaveTextContent("未分析");
    expect(screen.getByTestId("model-fold-fold2")).toHaveTextContent("未分析");
    expect(screen.getByTestId("model-fold-coverage-status")).toHaveTextContent("只作部分折诊断");
  });

  it("requests the selected supported feature for the live report diagnostic", async () => {
    setupWf(false);
    clientMock.getWorkflowContext.mockResolvedValue({ data: {
      schema_version: "1", battery_id: "CELL_001", experiment_id: "EXP_001", current_step: "REPORT",
      step_statuses: {}, artifact_freshness: {}, typed_actions: [],
      steps: { DATASET: { status: "COMPLETE", committed: { dataset_id: "DS::d1", selected_features: ["BOTTOM_AMP"] } } },
    }, meta: {} });
    clientMock.listReports.mockResolvedValue({ data: [{ report_id: "REPORT::fixture", generated_at: "2026-10-06" }], meta: {} });
    clientMock.getLimitations.mockResolvedValue({ data: { limitations: [] }, meta: {} });
    clientMock.getFeatureCorrelations.mockRejectedValue(new Error("fixture response"));
    wrap(<ReportWorkbench />, "/experiments/CELL_001/EXP_001/report", "/experiments/:batteryId/:experimentId/report");

    await waitFor(() => expect(clientMock.getFeatureCorrelations).toHaveBeenCalledWith(
      "CELL_001", "EXP_001", "BOTTOM_AMP", 300,
    ));
    expect(await screen.findByTestId("report-live-correlation-label")).toHaveTextContent("不属于上方已冻结的报告快照");
  });

  it("loads every supported selected feature and names unsupported selections", async () => {
    setupWf(false);
    clientMock.getWorkflowContext.mockResolvedValue({ data: {
      schema_version: "1", battery_id: "CELL_001", experiment_id: "EXP_001", current_step: "REPORT",
      step_statuses: {}, artifact_freshness: {}, typed_actions: [],
      steps: { DATASET: { status: "COMPLETE", committed: { dataset_id: "DS::d1", selected_features: ["SWA", "BOTTOM_AMP", "tof_us"] } } },
    }, meta: {} });
    clientMock.listReports.mockResolvedValue({ data: [{ report_id: "REPORT::fixture", generated_at: "2026-10-06" }], meta: {} });
    clientMock.getLimitations.mockResolvedValue({ data: { limitations: [] }, meta: {} });
    clientMock.getArtifact.mockResolvedValue({ data: { fields: { selected_features: ["SWA", "BOTTOM_AMP", "tof_us"] } }, meta: {} });
    clientMock.getFeatureCorrelations.mockRejectedValue(new Error("fixture response"));
    wrap(<ReportWorkbench />, "/experiments/CELL_001/EXP_001/report", "/experiments/:batteryId/:experimentId/report");

    await waitFor(() => expect(clientMock.getFeatureCorrelations).toHaveBeenCalledTimes(2));
    expect(clientMock.getFeatureCorrelations).toHaveBeenCalledWith("CELL_001", "EXP_001", "SWA", 300);
    expect(clientMock.getFeatureCorrelations).toHaveBeenCalledWith("CELL_001", "EXP_001", "BOTTOM_AMP", 300);
    expect(await screen.findByTestId("report-correlation-partial")).toHaveTextContent("未计算：tof_us");
    expect(screen.getByTestId("report-feature-correlation-SWA")).toBeInTheDocument();
    expect(screen.getByTestId("report-feature-correlation-BOTTOM_AMP")).toBeInTheDocument();
  });

  it("renders SOH state and cycle-group counts from the correlation response", async () => {
    setupWf(false);
    clientMock.getWorkflowContext.mockResolvedValue({ data: {
      schema_version: "1", battery_id: "CELL_001", experiment_id: "EXP_001", current_step: "REPORT",
      step_statuses: {}, artifact_freshness: {}, typed_actions: [],
      steps: { DATASET: { status: "COMPLETE", committed: { dataset_id: "DS::d1", selected_features: ["BOTTOM_AMP"] } } },
    }, meta: {} });
    clientMock.listReports.mockResolvedValue({ data: [{ report_id: "REPORT::fixture", generated_at: "2026-10-06" }], meta: {} });
    clientMock.getLimitations.mockResolvedValue({ data: { limitations: [] }, meta: {} });
    clientMock.getArtifact.mockResolvedValue({ data: { fields: { selected_features: ["BOTTOM_AMP"] } }, meta: {} });
    clientMock.listTargets.mockResolvedValue({ data: { targets: [
      {
        target_id: "temperature_c", display_name_en: "Temperature", display_name_zh: "温度",
        semantic_type: "DIRECT_MEASUREMENT", source: "Electrical record temperature channel",
        coverage: { valid: 36, total: 36 }, range: [23.1, 25.2], readiness: "BLOCKED_BY_VALIDATION",
        limitation: "sensor location/calibration evidence is not verified", unit: "celsius",
        provenance: {
          target_grain: "MEASUREMENT_EVENT", independent_unit: "BATTERY",
          method_id: "AUX_TEMP_RECORD_INDEX_JOIN", method_version: "0.5.1",
          definition: "Joined by electrical asset and record index; no sensor location inferred.",
          source_assets: [{ asset_id: "E001", source_reference: "electrical/CELL_001/EXP_001.xlsx", sha256: "e".repeat(64) }],
          observed_channels: ["T1"], uncertainty: { status: "UNKNOWN", reason: "Sensor location and calibration are not registered." },
        },
      },
      {
        target_id: "soh_capacity_reference_percent", display_name_en: "SOH", display_name_zh: "健康状态",
        semantic_type: "DERIVED_HEALTH_STATE", source: "Cycle-level capacity reference labels",
        coverage: { valid: 36, total: 36, independent_states: 2 }, range: [80, 90],
        readiness: "NOT_READY", limitation: "only 2 independent SOH states", unit: "percent",
        provenance: {
          target_grain: "CYCLE", independent_unit: "BATTERY",
          method_id: "SOH_CYCLE_CAPACITY_RATIO", method_version: "1.0.0",
          definition: "Cycle capacity normalized to declared reference capacity.",
          source_assets: [{ asset_id: "E001", source_reference: "electrical/CELL_001/EXP_001.xlsx", sha256: "e".repeat(64) }],
          uncertainty: { status: "UNKNOWN", reason: "Capacity-test measurement uncertainty is not characterized." },
        },
      },
    ] }, meta: {} });
    clientMock.getFeatureCorrelations.mockResolvedValue({ data: {
      feature_code: "BOTTOM_AMP", n_events: 36, soc: [{
        analysis_id: "overall-pearson", feature_code: "BOTTOM_AMP", gate_id: null,
        feature_variant: "RAW", state_variable: "reference_soc_percent", scope: "overall",
        method: "pearson", coefficient: 0.42, n_input: 36, n_input_unit: "MEASUREMENT_EVENT",
        n_valid: 35, n_valid_unit: "FEATURE_STATE_PAIR", independent_group_count: 1,
        independent_unit: "BATTERY", missing_feature_count: 1, missing_state_count: 0,
        excluded_ineligible_count: 0,
        limitations: ["event rows are repeated measures; no independent-event inference"],
        status: "VALID",
      }],
      soc_by_battery_condition: [{
        battery_id: "CELL_001", state_scope: "charge", coefficient: 0.42,
        n_input: 36, n_valid: 36, missing_feature_count: 0, missing_state_count: 0,
        excluded_ineligible_count: 0, status: "VALID",
      }],
      inference_assessment: {
        analysis_mode: "EXPLORATORY", claim_scope: "ASSOCIATION_ONLY",
        independent_unit: "BATTERY", correlation_results_included: true,
        study_protocol_status: "INCOMPLETE",
        analysis_plan: {
          status: "INCOMPLETE", study_id: "STUDY_A", plan_sha256: "abc123",
          matching_study_ids: ["STUDY_A"], invalid_plan_file_count: 0,
          unresolved_fields: ["primary_analysis.endpoint.unit"],
          approval_identity_status: "NOT_ASSESSED",
          approval_evidence_status: "NOT_ASSESSED",
          confirmatory_inference_enabled: false,
          scientific_validity: "NOT_ASSESSED", data_readiness: "NOT_ASSESSED",
        },
        confidence_interval: { status: "NOT_ESTIMATED", reason: "NO_PREREGISTERED_GROUPED_RESAMPLING_PLAN" },
        p_value: { status: "NOT_ESTIMATED", reason: "EVENT_ROWS_ARE_REPEATED_MEASURES" },
        multiple_comparison: { status: "NOT_ASSESSED", reason: "NO_PREDECLARED_TEST_FAMILY" },
        confounder_adjustment: { status: "NOT_ASSESSED", reason: "NO_PREDECLARED_CONFOUNDERS" },
      },
      temperature: {
        status: "VALID", coefficient: 0.42, n_input: 36, n_valid: 36,
        limitations: ["temperature variation screen: observed range 2.1 °C; 2 °C is only a minimum-variation screen, not sensor-calibration evidence or target readiness"],
      },
      soh: {
        status: "NOT_READY_INSUFFICIENT_SOH_STATES", n_input: 36, n_valid: 4,
        n_input_unit: "MEASUREMENT_EVENT", n_valid_unit: "BATTERY_EXPERIMENT_CYCLE_GROUP",
        missing_feature_count: 0, missing_state_count: 0,
        missing_count_unit: "MEASUREMENT_EVENT", excluded_ineligible_count: 0,
        excluded_ineligible_unit: "MEASUREMENT_EVENT",
        independent_group_count: 4, independent_unit: "BATTERY_EXPERIMENT_CYCLE",
        distinct_state_count: 1,
      },
      soc_cycle_decomposition: {
        policy: "CYCLE_WITHIN_BETWEEN_CORRELATION_V1", status: "VALID",
        interpretation: "BETWEEN_WITHIN_DIRECTION_DISAGREEMENT",
        n_input_events: 28, n_events: 24, n_cycle_groups: 3, n_batteries: 1,
        missing_feature_count: 2, missing_state_count: 1, excluded_ineligible_count: 1,
        within_cycle: { coefficient: 1, method: "PEARSON_ON_CYCLE_CENTERED_EVENT_VALUES", n_events: 24, n_cycle_groups: 3 },
        between_cycle: { coefficient: -1, method: "PEARSON_ON_CYCLE_MEANS", n_cycle_groups: 3 },
        limitations: ["Cycle groups are nested within Battery/Experiment and are not independent batteries"],
      },
      soc_battery_decomposition: {
        policy: "BATTERY_WITHIN_BETWEEN_CORRELATION_V1", status: "INSUFFICIENT_BATTERY_GROUPS",
        interpretation: "WITHIN_ONLY", n_input_events: 36, n_events: 35, n_batteries: 1,
        declared_battery_group_count: 1, physical_battery_count: null,
        battery_identity_status: "NOT_ASSESSED", group_count_semantics: "DECLARED_BATTERY_ID",
        missing_feature_count: 1, missing_state_count: 0, excluded_ineligible_count: 0,
        within_battery: { coefficient: 0.42, method: "PEARSON_ON_BATTERY_CENTERED_EVENT_VALUES", n_events: 35, n_batteries: 1 },
        between_battery: { coefficient: null, method: "PEARSON_ON_BATTERY_MEANS", n_batteries: 0, group_count_semantics: "DECLARED_BATTERY_ID" },
        limitations: ["event rows are not independent groups; no confidence interval or p-value is estimated"],
      },
      alignment_assessment: {
        status: "PROVISIONAL", validated_sync: false,
        association_scope: "EXPLORATORY_ONLY",
        limitation: "声电绝对时间基准未验证；与电学标签的关系仅作探索，不支持确认性结论。",
      },
      declared_condition_analysis: {
        status: "AVAILABLE", declaration_status: "OPERATOR_DECLARED",
        absolute_timebase_status: "NOT_ASSESSED", synchronization_status: "NOT_ASSESSED",
        segment_count: 1, events_assessed: 28,
        assignment_status_counts: { ASSIGNED_OPERATOR_DECLARED_SAME_ASSET_CLOCK: 24, UNCLASSIFIED_NO_SEGMENT: 4 },
        results: [{
          feature_code: "BOTTOM_AMP", policy: "OPERATOR_DECLARED_CONDITION_SOC_STRATIFICATION_V1",
          feature_variant: "RAW", gate_id: null, condition_axis_id: "temperature_setpoint",
          condition_value: "25", unit: "degC", declaration_status: "OPERATOR_DECLARED",
          absolute_timebase_status: "NOT_ASSESSED", synchronization_status: "NOT_ASSESSED",
          method: "pearson", coefficient: 0.42, n_input_events: 28, n_valid_pairs: 24,
          missing_feature_count: 1, missing_state_count: 2, excluded_ineligible_count: 1,
          battery_count: 1, cycle_count: 3, segment_ids: ["SEG_25C"],
          time_reference_asset_ids: ["U001"], analysis_mode: "EXPLORATORY", status: "VALID",
          limitations: ["operator-declared; timebase not assessed; descriptive only"],
        }],
        limitations: ["工况为操作者申报；绝对时基和同步未评估。"],
      },
      soh_cycle_summary: [],
    }, meta: {} } as never);
    wrap(<ReportWorkbench />, "/experiments/CELL_001/EXP_001/report", "/experiments/:batteryId/:experimentId/report");

    expect(await screen.findByTestId("report-soh-accounting")).toHaveTextContent("有效分析单位为 BATTERY_EXPERIMENT_CYCLE_GROUP，共 4 个有效组");
    expect(await screen.findByTestId("report-soc-estimate-audit")).toHaveTextContent("有效配对 35/36 FEATURE_STATE_PAIR");
    expect(screen.getByTestId("report-soc-estimate-audit")).toHaveTextContent("输入单位 MEASUREMENT_EVENT");
    expect(screen.getByTestId("report-soc-estimate-audit")).toHaveTextContent("event rows are repeated measures");
    expect(screen.getByTestId("report-soc-estimate-audit")).toHaveTextContent("声明分组 1 BATTERY");
    expect(screen.getByTestId("report-inference-assessment")).toHaveTextContent("组身份 NOT_ASSESSED");
    expect(screen.getByTestId("report-battery-decomposition")).toHaveTextContent("物理电池身份未独立审核");
    expect(screen.getByTestId("report-soc-estimate-audit")).toHaveTextContent("区间 NOT_ESTIMATED");
    expect(screen.getByTestId("report-soh-accounting")).toHaveTextContent("输入/缺失/排除计数以 MEASUREMENT_EVENT 计，输入 36");
    expect(screen.getByTestId("report-temperature-correlation")).toHaveTextContent("Pearson r 0.420，完整配对 36/36");
    expect(screen.getByTestId("report-temperature-correlation")).toHaveTextContent("not sensor-calibration evidence or target readiness");
    expect(await screen.findByTestId("report-temperature-provenance")).toHaveTextContent("BLOCKED_BY_VALIDATION");
    expect(screen.getByTestId("report-temperature-provenance")).toHaveTextContent("AUX_TEMP_RECORD_INDEX_JOIN");
    expect(screen.getByTestId("report-temperature-provenance")).toHaveTextContent("T1");
    expect(screen.getByTestId("report-temperature-provenance")).toHaveTextContent("Sensor location and calibration are not registered");
    expect(await screen.findByTestId("report-soh-provenance")).toHaveTextContent("CYCLE");
    expect(screen.getByTestId("report-soh-provenance")).toHaveTextContent("SOH_CYCLE_CAPACITY_RATIO");
    expect(screen.getByTestId("report-soh-provenance")).toHaveTextContent("only 2 independent SOH states");
    expect(screen.getByTestId("report-condition-slices")).toHaveTextContent("按 Battery / 充放电阶段");
    expect(screen.getByTestId("report-condition-slices")).toHaveTextContent("CELL_001 · 充电");
    expect(screen.getByTestId("report-condition-slices")).toHaveTextContent("是电化学阶段切片，不是实验工况切片");
    expect(screen.getByTestId("report-cycle-decomposition")).toHaveTextContent("Cycle 组间与组内方向相反，整体相关可能误导");
    expect(screen.getByTestId("report-cycle-decomposition")).toHaveTextContent("有效事件 24/28");
    expect(screen.getByTestId("report-cycle-decomposition")).toHaveTextContent("缺失特征 2、状态 1、同步排除 1");
    expect(screen.getByTestId("report-cycle-decomposition")).toHaveTextContent("Cycle groups are nested within Battery/Experiment");
    expect(screen.getByTestId("report-battery-decomposition")).toHaveTextContent("event rows are not independent groups");
    expect(screen.getByTestId("report-alignment-assessment")).toHaveTextContent("PROVISIONAL");
    expect(screen.getByTestId("report-alignment-assessment")).toHaveTextContent("不支持确认性结论");
    expect(screen.getByTestId("report-inference-assessment")).toHaveTextContent("研究方案 INCOMPLETE；Study STUDY_A；审批身份核验 NOT_ASSESSED / 审批证据 NOT_ASSESSED；未解决项 1；确认性推断 未启用");
    expect(screen.getByTestId("report-inference-assessment")).toHaveTextContent("审批身份核验 NOT_ASSESSED / 审批证据 NOT_ASSESSED");
    expect(screen.getByTestId("report-declared-condition-analysis")).toHaveTextContent("按显式申报工况查看 SOC 关系（AVAILABLE）");
    expect(screen.getByTestId("report-declared-condition-analysis")).toHaveTextContent("temperature_setpoint = 25 degC");
    expect(screen.getByTestId("report-declared-condition-analysis")).toHaveTextContent("有效配对 24/28");
  });

  it("renders registry strategies as selectable checkboxes with Dummy preselected", async () => {
    setupWf(true);
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    const mlp = await screen.findByTestId("modeling-strategy-MLP_REGRESSOR");
    expect(mlp).not.toBeChecked();
    expect(await screen.findByTestId("modeling-strategy-DUMMY_MEAN")).toBeChecked();
  });

  it("runs the grouped split pipeline in-page when split is missing", async () => {
    setupWf(false);
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("launcher-create-split"));
    await waitFor(() => expect(clientMock.startRun).toHaveBeenCalledWith({
      profile: "EVALUATION_SPLIT",
      battery_id: "CELL_001", experiment_id: "EXP_001",
      target: "soc_reference_percent",
      features: { selected_features: ["SWA"] },
      split: { strategy: "LEAVE_ONE_GROUP_OUT", split_unit: "CYCLE", group_column: "cycle_group_id" },
    }));
  });

  it("does not present partial-fold metrics as a complete model conclusion", async () => {
    setupWf(true);
    clientMock.getResults.mockResolvedValue({ data: [
      { result_id: "R::dummy", result_type: "MODEL_COMPARISON", strategy: "DUMMY_MEAN", value: 31,
        units: "percent", scope: "experiment", dataset_id: "DS::d1", split_id: "SPLIT::s1",
        scientific_status: "PARTIAL_FOLD_COVERAGE", limitations: ["PARTIAL_FOLD_COVERAGE"] },
      { result_id: "R::ridge", result_type: "MODEL_COMPARISON", strategy: "RIDGE", value: 30,
        units: "percent", scope: "experiment", dataset_id: "DS::d1", split_id: "SPLIT::s1",
        scientific_status: "PARTIAL_FOLD_COVERAGE", limitations: ["PARTIAL_FOLD_COVERAGE"] },
    ], meta: {} } as never);
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");

    expect(await screen.findByText("当前只有部分 folds 的诊断结果，不能判断完整 Split 是否跑赢 Dummy。")).toBeInTheDocument();
    expect(screen.getByText("诊断结果 · 折覆盖不全")).toBeInTheDocument();
    expect(screen.getByTestId("model-comparison-current")).toHaveTextContent("折覆盖不全 · 仅诊断");
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
    clientMock.listReports.mockResolvedValue({ data: [{ report_id: "REPORT::old", generated_at: "2025-01-01", scientific_findings: ["Old finding"], report_freshness: { status: "SUPERSEDED", reasons: ["NEWER_REPORT_EXISTS"] } }], meta: {} });
    clientMock.getLimitations.mockResolvedValue({ data: { limitations: [] }, meta: {} });
    clientMock.getFeatureCorrelations.mockResolvedValue({ data: { soc: [], soc_battery_decomposition: { policy: "BATTERY_WITHIN_BETWEEN_CORRELATION_V1", status: "INSUFFICIENT_BATTERY_GROUPS", interpretation: "WITHIN_ONLY", n_input_events: 4000, n_events: 3995, n_batteries: 1, missing_feature_count: 0, missing_state_count: 5, excluded_ineligible_count: 0, within_battery: { coefficient: 0.42, method: "PEARSON_ON_BATTERY_CENTERED_EVENT_VALUES", n_events: 3995, n_batteries: 1 }, between_battery: { coefficient: null, method: "PEARSON_ON_BATTERY_MEANS", n_batteries: 0 }, limitations: [] }, soc_by_battery_condition: [{ battery_id: "CELL_001", state_scope: "charge", scope: "battery:CELL_001:charge", coefficient: 0.5, n_valid: 120, missing_feature_count: 0, missing_state_count: 0, excluded_ineligible_count: 0, status: "VALID", analysis_id: "a", feature_code: "SWA", gate_id: null, feature_variant: "RAW", state_variable: "reference_soc_percent", method: "pearson", limitations: [] }], soc_by_cycle: [], inference_assessment: { analysis_mode: "EXPLORATORY", claim_scope: "ASSOCIATION_ONLY", independent_unit: "BATTERY", study_protocol_status: "NOT_REGISTERED", confidence_interval: { status: "NOT_ESTIMATED", reason: "NO_PREREGISTERED_GROUPED_RESAMPLING_PLAN" }, p_value: { status: "NOT_ESTIMATED", reason: "EVENT_ROWS_ARE_REPEATED_MEASURES" }, multiple_comparison: { status: "NOT_ASSESSED", reason: "NO_PREDECLARED_TEST_FAMILY" }, confounder_adjustment: { status: "NOT_ASSESSED", reason: "NO_PREDECLARED_CONFOUNDERS" } }, temperature: { status: "TEMPERATURE_UNAVAILABLE" }, soh: { status: "NOT_READY_INSUFFICIENT_SOH_STATES" }, declared_condition_analysis: { status: "NOT_CONFIGURED", declaration_status: "NOT_CONFIGURED", absolute_timebase_status: "NOT_ASSESSED", synchronization_status: "NOT_ASSESSED", segment_count: 0, events_assessed: 0, assignment_status_counts: {}, results: [], limitations: ["condition_segments.csv is not configured"] }, soh_cycle_summary: [] }, meta: {} });
    clientMock.getArtifact.mockResolvedValue({ data: { fields: { selected_features: ["tof_us"] } }, meta: {} });
    wrap(<ReportWorkbench />, "/experiments/CELL_001/EXP_001/report", "/experiments/:batteryId/:experimentId/report");
    expect(await screen.findByTestId("report-snapshot-stale")).toHaveTextContent("SUPERSEDED");
    expect(screen.getByTestId("report-snapshot-stale")).toHaveTextContent("NEWER_REPORT_EXISTS");
    expect(await screen.findByTestId("report-correlation-unavailable")).toHaveTextContent("不会改用其他特征代替");
    expect(screen.getByTestId("report-live-correlation-label")).toHaveTextContent("不属于上方已冻结的报告快照");
    expect(clientMock.getFeatureCorrelations).not.toHaveBeenCalled();
    expect(screen.getByTestId("report-current-models-missing")).toHaveTextContent("DS::current");
    expect(screen.getByRole("button", { name: /生成报告/ })).toBeDisabled();
  });

  it("hides frozen report claims and export when source integrity is blocked", async () => {
    clientMock.getWorkflowContext.mockResolvedValue({ data: {
      schema_version: "1", battery_id: "CELL_001", experiment_id: "EXP_001", current_step: "DATASET",
      step_statuses: { REPORT: "BLOCKED" }, artifact_freshness: { report: "INTEGRITY_BLOCKED" }, typed_actions: [], steps: {},
    }, meta: {} });
    clientMock.getResults.mockResolvedValue({ data: [], meta: {} });
    clientMock.listReports.mockResolvedValue({ data: [{ report_id: "REPORT::untrusted", generated_at: "2026-01-01", scientific_findings: ["untrusted frozen finding"], report_freshness: { status: "INTEGRITY_BLOCKED", reasons: ["SOURCE_PROVENANCE_INVALID:ELECTRICAL"] } }], meta: {} });
    wrap(<ReportWorkbench />, "/experiments/CELL_001/EXP_001/report", "/experiments/:batteryId/:experimentId/report");

    expect(await screen.findByTestId("report-integrity-blocked")).toHaveTextContent("SOURCE_PROVENANCE_INVALID:ELECTRICAL");
    expect(screen.queryByText("untrusted frozen finding")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /导出 JSON/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /查看运行记录与恢复步骤/ })).toHaveAttribute("href", "/experiments/CELL_001/EXP_001/runs");
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

  it("does not treat an identity-unreviewed cohort as cross-battery evidence", async () => {
    setupWf(true);
    clientMock.listCohortDatasets.mockResolvedValue({ data: [{
      cohort_id: "COHORT::fixture", cohort_dataset_id: "COHORT::version", status: "READY_FOR_BATTERY_SPLIT",
      battery_count: 3, identity_verification_status: "NOT_ASSESSED", scientific_generalization_eligible: false,
      row_count: 12, predictor_columns: ["p2p"], target_column: "reference_soc_percent",
      source_datasets: [{ source_dataset_id: "DS::A", battery_id: "CELL_001", experiment_id: "EXP_001" }],
    }], meta: {} });
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    expect(await screen.findByTestId("cohort-lobo-blocked")).toHaveTextContent("实体身份经过独立审核");
    expect(screen.queryByTestId("run-cohort-lobo")).not.toBeInTheDocument();
  });

  it("runs LOBO only for a verified cohort containing the current experiment", async () => {
    setupWf(true);
    clientMock.listCohortDatasets.mockResolvedValue({ data: [{
      cohort_id: "COHORT::fixture", cohort_dataset_id: "COHORT::version", status: "READY_FOR_BATTERY_SPLIT",
      battery_count: 3, identity_verification_status: "VERIFIED", scientific_generalization_eligible: true,
      row_count: 12, predictor_columns: ["p2p"], target_column: "reference_soc_percent",
      source_datasets: [{ source_dataset_id: "DS::A", battery_id: "CELL_001", experiment_id: "EXP_001" }],
    }], meta: {} });
    clientMock.runCohortLOBO.mockResolvedValue({ data: {
      evaluation_id: "LOBO::fixture", evaluation_scope: "DECLARED_GROUP_LOBO_TECHNICAL_EVALUATION",
      battery_count: null, declared_group_count: 3, identity_verification_status: "NOT_ASSESSED",
      scientific_generalization_eligible: false, group_identity_status: "NOT_ASSESSED", split_unit: "DECLARED_BATTERY_ID", fold_count: 3,
      pooled_row_diagnostic_by_strategy: { DUMMY_MEAN: { MAE: 20.4 } },
      declared_group_results: [{ strategy: "DUMMY_MEAN", declared_group_id: "CELL_B", held_out_declared_group_id: "CELL_B", train_declared_group_ids: ["CELL_A", "CELL_C"], fold: "fold2", overall: { MAE: 22.1 }, row_count: 4 }],
      macro_by_strategy: { DUMMY_MEAN: { macro_MAE: 22.1, macro_RMSE: 25, declared_group_count: 3, aggregation: "MACRO_MEAN_OF_BATTERY_METRICS" } },
      held_out_prediction_coverage: { status: "COMPLETE", independent_unit: "DECLARED_BATTERY_ID", expected_declared_group_count: 3, declared_group_count: 3, observed_declared_group_count_per_strategy: { DUMMY_MEAN: 3 }, expected_prediction_rows: 12, observed_prediction_rows: 12, expected_unique_event_count_per_strategy: 12 },
      uncertainty_assessment: { independent_unit: "DECLARED_BATTERY_ID", independent_group_count: null, declared_group_count: 3, group_identity_status: "NOT_ASSESSED", confidence_interval: { status: "NOT_ESTIMATED", reason: "NO_PREREGISTERED_GROUPED_RESAMPLING_PLAN", resampling_unit: "DECLARED_BATTERY_ID" } },
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
    expect(screen.getByTestId("cohort-lobo-uncertainty")).toHaveTextContent("置信区间未估计");
    expect(screen.getByTestId("cohort-lobo-uncertainty")).toHaveTextContent("不能视为独立 Battery 数");
    expect(screen.getByTestId("cohort-lobo-coverage")).toHaveTextContent("12 / 12 行");
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
