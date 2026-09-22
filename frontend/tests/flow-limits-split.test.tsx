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
  createSplit: vi.fn(),
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
  clientMock.createSplit.mockResolvedValue({ data: { split_id: "SPLIT::new99", status: "REUSED" }, meta: {} });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [{ path: "/experiments/:batteryId/:experimentId/*", element: <AnalysisWorkbench /> }],
    { initialEntries: ["/experiments/CELL_001/EXP_001/analysis?step=selection"] },
  );
  return render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>);
}

describe("in-flow grouped split creation (Limit-1)", () => {
  it("offers create-split when ML-safe has no split but a canonical dataset exists", async () => {
    setup();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("mode-mlsafe"));
    const btn = await screen.findByTestId("create-split-btn", {}, { timeout: 4000 });
    await user.click(btn);
    await waitFor(() => {
      expect(clientMock.createSplit).toHaveBeenCalledWith({
        battery_id: "CELL_001", experiment_id: "EXP_001", dataset_id: "DS::abc123",
      });
    });
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
