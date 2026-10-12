/**
 * Flow-limit fixes: in-flow grouped split creation (Limit-1).
 * When ML-safe mode has no split yet but a canonical dataset exists,
 * Step 5 must offer "创建分组划分" and POST /splits for that dataset.
 * @vitest-environment jsdom
 */
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

const clientMock = {
  listTargets: vi.fn(),
  listFeatures: vi.fn(),
  listFeatureDefinitions: vi.fn(),
  listMaterializedAnalyses: vi.fn(),
  listSplits: vi.fn(),
  listSplitFolds: vi.fn(),
  getExperiment: vi.fn(),
  getWorkflowContext: vi.fn(),
  createSplit: vi.fn(),
  startRun: vi.fn(),
  postFeatureTargetRanking: vi.fn(),
  getAlignmentSummary: vi.fn(),
};
vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  client: clientMock,
}));

const { AnalysisWorkbench } = await import("../src/pages/redesign/AnalysisWorkbench");

function setup(datasetId: string | null = "DS::abc123") {
  clientMock.listTargets.mockResolvedValue({ data: { targets: [{
    target_id: "reference_soc_percent", display_name_en: "Reference SOC", display_name_zh: "参考SOC",
    semantic_type: "DERIVED_REFERENCE_LABEL", source: "s", coverage: { valid: 3995, total: 3999 },
    range: [0, 100], readiness: "READY_FOR_LIMITED_EVALUATION", limitation: "l", limitation_zh: "l", unit: "percent",
  }] }, meta: {} });
  clientMock.listFeatures.mockResolvedValue({ data: { features: [] }, meta: {} });
  clientMock.listFeatureDefinitions.mockResolvedValue({ data: { catalogue: [], formula_source_id: "S" }, meta: {} });
  clientMock.listMaterializedAnalyses.mockResolvedValue({ data: { analyses: [] }, meta: {} });
  clientMock.listSplits.mockResolvedValue({ data: { splits: [] }, meta: {} });
  clientMock.getExperiment.mockResolvedValue({ data: { latest_canonical_artifacts: datasetId ? { dataset_id: datasetId } : {} }, meta: {} });
  clientMock.getWorkflowContext.mockResolvedValue({ data: {
    steps: {
      TARGET: { committed: { target_id: "reference_soc_percent" } },
      FEATURES: { committed: { selected_features: ["waveform_rms_a_u"] } },
      DATASET: { committed: { selected_features: ["waveform_rms_a_u"] } },
    },
  }, meta: {} });
  clientMock.startRun.mockResolvedValue({ data: {
    run_id: "RUN::split", status: "SUCCEEDED",
    final_artifacts: [{ artifact_type: "SPLIT", artifact_id: "SPLIT::new99" }],
  }, meta: {} });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [{ path: "/experiments/:batteryId/:experimentId/*", element: <AnalysisWorkbench /> }],
    { initialEntries: ["/experiments/CELL_001/EXP_001/analysis?step=selection"] },
  );
  return render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>);
}

describe("in-flow grouped split materialization (Limit-1)", () => {
  it("runs the grouped split pipeline when ML-safe has no split but a canonical dataset exists", async () => {
    setup();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("mode-mlsafe"));
    const btn = await screen.findByTestId("create-split-btn", {}, { timeout: 4000 });
    await user.click(btn);
    await waitFor(() => {
      expect(clientMock.startRun).toHaveBeenCalledWith({
        profile: "EVALUATION_SPLIT",
        battery_id: "CELL_001", experiment_id: "EXP_001",
        target: "soc_reference_percent",
        features: { selected_features: ["waveform_rms_a_u"] },
        split: { strategy: "LEAVE_ONE_GROUP_OUT", split_unit: "CYCLE", group_column: "cycle_group_id" },
      });
    });
  });

  it("does not claim split completion when the run is waiting for a user action", async () => {
    setup();
    clientMock.startRun.mockResolvedValueOnce({ data: {
      run_id: "RUN::waiting", status: "WAITING_FOR_USER", final_artifacts: [],
    }, meta: {} });
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("mode-mlsafe"));
    await user.click(await screen.findByTestId("create-split-btn", {}, { timeout: 4000 }));
    const failure = await screen.findByRole("alert");
    expect(failure).toHaveTextContent("RUN::waiting");
    expect(failure).toHaveTextContent("WAITING_FOR_USER");
    expect(screen.getByRole("link", { name: "查看运行" })).toHaveAttribute("href", "/runs");
    expect(screen.queryByText(/分组划分运行已完成/)).not.toBeInTheDocument();
  });

  it("falls back to the Advanced link when no canonical dataset exists", async () => {
    setup(null);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("mode-mlsafe"));
    await waitFor(() => expect(clientMock.getExperiment).toHaveBeenCalled());
    expect(screen.queryByTestId("create-split-btn")).not.toBeInTheDocument();
    expect(screen.getByText(/Dataset Split/)).toBeInTheDocument();
  });
});
