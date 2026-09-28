/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const clientMock = {
  getWorkflowContext: vi.fn(), listTargets: vi.fn(), listFeatures: vi.fn(), listFeatureDefinitions: vi.fn(),
  listMaterializedAnalyses: vi.fn(), listSplits: vi.fn(), getExperiment: vi.fn(), listSplitFolds: vi.fn(),
  createSplit: vi.fn(),
};
vi.mock("../src/api/client", async importOriginal => ({
  ...(await importOriginal<typeof import("../src/api/client")>()), client: clientMock,
}));

const { AnalysisWorkbench } = await import("../src/pages/redesign/AnalysisWorkbench");

function mount() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([{ path: "/experiments/:batteryId/:experimentId/analysis", element: <AnalysisWorkbench /> }], {
    initialEntries: ["/experiments/CELL_001/EXP_001/analysis?step=features"],
  });
  return render(<QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  clientMock.getWorkflowContext.mockResolvedValue({ data: {
    schema_version: "workflow-context/1.0", battery_id: "CELL_001", experiment_id: "EXP_001", current_step: "FEATURES",
    step_statuses: {}, steps: {
      TARGET: { status: "COMPLETE", committed: { target_id: "reference_soc_percent" } },
      FEATURES: { status: "COMPLETE", committed: { analysis_mode: "TRAIN_ONLY_ML_SAFE", selected_features: ["tof_us", "amplitude_a_u"] } },
      DATASET: { status: "COMPLETE", committed: { dataset_id: "DS::current", selected_features: ["legacy_feature"] } },
    }, recommended_next_action: null, pending_action: null, artifact_freshness: {},
    scientific_context: {}, assistant_context: {}, typed_actions: [], meta: { read_only: true, no_recomputation: true },
  }, meta: {} });
  clientMock.listTargets.mockResolvedValue({ data: { targets: [{
    target_id: "reference_soc_percent", display_name_en: "Reference SOC", display_name_zh: "参考 SOC",
    semantic_type: "DERIVED_REFERENCE_LABEL", source: "Electrical XLSX", coverage: { valid: 2, total: 2 },
    range: [0, 100], readiness: "READY_FOR_LIMITED_EVALUATION", limitation: "retrospective", unit: "%",
  }] }, meta: {} });
  clientMock.listFeatures.mockResolvedValue({ data: { features: [
    { feature_name: "tof_us", availability: "AVAILABLE" }, { feature_name: "amplitude_a_u", availability: "AVAILABLE" },
  ] }, meta: {} });
  clientMock.listFeatureDefinitions.mockResolvedValue({ data: { formula_source_id: "S", formula_policy_version: "P", catalogue: [
    { code: "tof_us", display_name_en: "Time of Flight", display_name_zh: "飞行时间", family: "TD", units: "μs", formula_source_id: "S", formula_policy_version: "P", formula_text: "—", definition_status: "DEFINED_AND_VALIDATED", parity_status: "PASS", existing_alias: null, scope: ["FULL_WAVEFORM"] },
    { code: "amplitude_a_u", display_name_en: "Amplitude", display_name_zh: "幅值", family: "TD", units: "a.u.", formula_source_id: "S", formula_policy_version: "P", formula_text: "—", definition_status: "DEFINED_AND_VALIDATED", parity_status: "PASS", existing_alias: null, scope: ["FULL_WAVEFORM"] },
  ] }, meta: {} });
  clientMock.listMaterializedAnalyses.mockResolvedValue({ data: { analyses: [] }, meta: {} });
  clientMock.listSplits.mockResolvedValue({ data: { splits: [{ split_id: "SPLIT::1", strategy: "LEAVE_ONE_GROUP_OUT" }] }, meta: {} });
  clientMock.getExperiment.mockResolvedValue({ data: { latest_canonical_artifacts: { dataset_id: "DS::current" } }, meta: {} });
  clientMock.listSplitFolds.mockResolvedValue({ data: { folds: [{ fold: "fold1", train_rows: 2, held_out_rows: 1 }] }, meta: {} });
});

describe("AnalysisWorkbench committed draft hydration", () => {
  it("restores the committed selection instead of showing an empty catalogue on entry", async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId("quick-tof_us")).toBeChecked());
    expect(screen.getByTestId("quick-amplitude_a_u")).toBeChecked();
    expect(screen.getByText("已选 2 个特征")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Time of Flight" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Amplitude" })).toBeChecked();
  });

  it("follows an in-app recovery deep link and restores target on the Dataset step", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const router = createMemoryRouter([{ path: "/experiments/:batteryId/:experimentId/analysis", element: <AnalysisWorkbench /> }], {
      initialEntries: ["/experiments/CELL_001/EXP_001/analysis?step=features"],
    });
    render(<QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByTestId("quick-tof_us")).toBeChecked());
    await act(async () => { await router.navigate("/experiments/CELL_001/EXP_001/analysis?step=dataset"); });
    await waitFor(() => expect(screen.getByTestId("step-dataset")).toBeInTheDocument());
    expect(screen.getByTestId("step-dataset")).toHaveTextContent("Target (y) = Reference SOC / 参考 SOC");
    expect(screen.getByTestId("step-dataset")).toHaveTextContent("所选超声特征（2）");
  });
});
