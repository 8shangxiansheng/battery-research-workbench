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
  getArtifact: vi.fn(),
};
vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  client: clientMock,
}));

const { RunsPage } = await import("../src/pages/RunsPage");
const { ModelsWorkbench } = await import("../src/pages/redesign/ModelsWorkbench");

function wrap(node: React.ReactNode, route = "/runs", pattern = route) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([{ path: pattern, element: node }], { initialEntries: [route] });
  return render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>);
}

beforeEach(() => { vi.clearAllMocks(); });

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
      "RUN::r1", "UA::P1", { "ultrasound.sampling_rate_hz": { value: 50, unit: "MHz" } }));
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
      steps: { DATASET: { status: "COMPLETE", committed: { dataset_id: "DS::d1" } },
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
    const btn = await screen.findByTestId("launcher-start-run");
    await waitFor(() => expect(btn).toBeEnabled());
    await user.click(btn);
    await waitFor(() => expect(clientMock.startRun).toHaveBeenCalledWith({
      profile: "FULL_PRE_MODEL", battery_id: "CELL_001", experiment_id: "EXP_001" }));
  });

  it("offers in-page split creation when split is missing", async () => {
    setupWf(false);
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("launcher-create-split"));
    await waitFor(() => expect(clientMock.createSplit).toHaveBeenCalledWith({
      battery_id: "CELL_001", experiment_id: "EXP_001", dataset_id: "DS::d1" }));
  });

  it("blocks starting while a run waits for user confirmation", async () => {
    setupWf(true, [{ run_id: "RUN::w", status: "WAITING_FOR_USER", experiment_id: "EXP_001" }]);
    wrap(<ModelsWorkbench />, route, "/experiments/:batteryId/:experimentId/models");
    expect(await screen.findByTestId("launcher-waiting-run")).toBeInTheDocument();
    expect(screen.getByTestId("launcher-start-run")).toBeDisabled();
  });
});
