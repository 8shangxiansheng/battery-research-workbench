/** @vitest-environment jsdom */
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const clientMock = {
  listFeatures: vi.fn(),
  getExperiment: vi.fn(),
  startRun: vi.fn(),
  createDataset: vi.fn(),
  createSplit: vi.fn(),
};
vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  client: clientMock,
}));

const { DatasetSplitPage } = await import("../src/pages/DatasetSplitPage");

describe("Advanced Dataset & Split workflow", () => {
  it("materializes Dataset and grouped Split through orchestrator runs", async () => {
    clientMock.listFeatures.mockResolvedValue({
      data: { features: [{ feature_name: "waveform_rms_a_u", availability: "AVAILABLE" }] },
      meta: {},
    });
    clientMock.getExperiment.mockResolvedValue({
      data: { latest_canonical_artifacts: {} },
      meta: {},
    });
    clientMock.startRun
      .mockResolvedValueOnce({
        data: {
          run_id: "RUN::dataset",
          status: "SUCCEEDED",
          final_artifacts: [{ artifact_type: "DATASET", artifact_id: "DS::fresh", status: "READY_WITH_LIMITATIONS" }],
        },
        meta: {},
      })
      .mockResolvedValueOnce({
        data: {
          run_id: "RUN::split",
          status: "SUCCEEDED",
          final_artifacts: [{ artifact_type: "SPLIT", artifact_id: "SPLIT::fresh" }],
        },
        meta: {},
      });

    const router = createMemoryRouter(
      [{ path: "/experiments/:batteryId/:experimentId/advanced/dataset-split", element: <DatasetSplitPage /> }],
      { initialEntries: ["/experiments/CELL_001/EXP_001/advanced/dataset-split"] },
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>);

    const user = userEvent.setup();
    await user.click(await screen.findByLabelText("waveform_rms_a_u"));
    await user.click(screen.getByTestId("create-dataset"));
    await waitFor(() => expect(clientMock.startRun).toHaveBeenNthCalledWith(1, {
      profile: "BUILD_DATASET",
      battery_id: "CELL_001",
      experiment_id: "EXP_001",
      target: "soc_reference_percent",
      features: { selected_features: ["waveform_rms_a_u"] },
    }));
    await user.click(await screen.findByTestId("create-split"));
    await waitFor(() => expect(clientMock.startRun).toHaveBeenNthCalledWith(2, {
      profile: "EVALUATION_SPLIT",
      battery_id: "CELL_001",
      experiment_id: "EXP_001",
      target: "soc_reference_percent",
      features: { selected_features: ["waveform_rms_a_u"] },
      split: { strategy: "LEAVE_ONE_GROUP_OUT", split_unit: "CYCLE", group_column: "cycle_group_id" },
    }));
    expect(await screen.findByText(/SPLIT::fresh/)).toBeInTheDocument();
    expect(clientMock.createDataset).not.toHaveBeenCalled();
    expect(clientMock.createSplit).not.toHaveBeenCalled();
  });
});
