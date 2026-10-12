/** @vitest-environment jsdom */
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const clientMock = {
  getResearchOverview: vi.fn(),
  startRun: vi.fn(),
  getWorkflowContext: vi.fn(),
};
vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  client: clientMock,
}));

const { TemperatureChannelSelectionPanel } = await import(
  "../src/components/workbench/TemperatureChannelSelectionPanel"
);

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [{ path: "/", element: <TemperatureChannelSelectionPanel batteryId="CELL_X" experimentId="EXP_X" /> },
      { path: "/runs", element: <p>Runs</p> }],
    { initialEntries: ["/"] },
  );
  return render(<QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>);
}

describe("TemperatureChannelSelectionPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("requires an explicit real channel and submits it in the ingest run plan", async () => {
    clientMock.getResearchOverview.mockResolvedValue({ data: {
      metadata: { temperature: { status: "AVAILABLE", channel: ["T1", "T2"] } },
    }, meta: {} });
    clientMock.startRun.mockResolvedValue({ data: { run_id: "RUN::temp-channel" }, meta: {} });
    renderPanel();
    const user = userEvent.setup();

    const select = await screen.findByTestId("temperature-channel-select");
    expect(select).toHaveValue("");
    await user.selectOptions(select, "T2");
    await user.click(screen.getByTestId("rebuild-temperature-channel"));

    await waitFor(() => expect(clientMock.startRun).toHaveBeenCalledWith({
      profile: "INGEST_TO_MEASUREMENT_EVENTS",
      battery_id: "CELL_X",
      experiment_id: "EXP_X",
      measurement_events: { temperature_channel_id: "T2" },
    }));
    expect(await screen.findByTestId("temperature-channel-run-started")).toHaveTextContent("不会因此自动升级");
  });

  it("does not invent a channel when none is available", async () => {
    clientMock.getResearchOverview.mockResolvedValue({ data: {
      metadata: { temperature: { status: "NOT_CONFIGURED", channel: null } },
    }, meta: {} });
    renderPanel();

    expect(await screen.findByTestId("temperature-channel-unavailable")).toHaveTextContent("不会猜测或合并通道");
    expect(clientMock.startRun).not.toHaveBeenCalled();
  });

  it("preselects the only observed channel but still requires an explicit rebuild action", async () => {
    clientMock.getResearchOverview.mockResolvedValue({ data: {
      metadata: { temperature: { status: "AVAILABLE", channel: ["T1"] } },
    }, meta: {} });
    renderPanel();

    expect(await screen.findByTestId("temperature-channel-select")).toHaveValue("T1");
    expect(clientMock.startRun).not.toHaveBeenCalled();
  });
});
