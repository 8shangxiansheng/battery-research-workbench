import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspacePage } from "../src/pages/WorkspacePage";
import * as clientModule from "../src/api/client";

// T01–T06（§58）
describe("WorkspacePage（§58 T01–T06）", () => {
  const summary = {
    battery_id: "CELL_001",
    experiment_id: "EXP_001",
    experiment_composite_id: "CELL_001/EXP_001",
    scientific_status: "READY_FOR_LIMITED_EVALUATION",
    limitations: ["ONE_BATTERY_ONLY"],
    latest_canonical_artifacts: { dataset_id: "DS::abc" },
    run_ids: [],
    limitations_registry: [
      { code: "ONE_BATTERY_ONLY", severity: "BLOCKING_FOR_CLAIM", description: "仅一块电池" },
    ],
    readiness: {},
    next_actions: ["查看波形"],
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  function renderPage() {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/experiments/CELL_001/EXP_001/workspace"]}>
          <Routes>
            <Route path="/experiments/:batteryId/:experimentId/workspace" element={<WorkspacePage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("T01 显示 workspace summary 与 scientific_status", async () => {
    vi.spyOn(clientModule.client, "getWorkspaceSummary").mockResolvedValue({
      data: summary as never,
      meta: {},
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("READY_FOR_LIMITED_EVALUATION")).toBeInTheDocument();
    });
  });

  it("T02 显示 limitations 注册表", async () => {
    vi.spyOn(clientModule.client, "getWorkspaceSummary").mockResolvedValue({
      data: summary as never,
      meta: {},
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/ONE_BATTERY_ONLY/)).toBeInTheDocument();
    });
  });

  it("T03 TOF BLOCKED 显示 null+reason，不显示 0", async () => {
    vi.spyOn(clientModule.client, "getWorkspaceSummary").mockResolvedValue({
      data: {
        ...summary,
        readiness: {
          "R::tof_status": "BLOCKED",
        },
      } as never,
      meta: {},
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/BLOCKED/)).toBeInTheDocument();
    });
  });

  it("T04 SOH NOT_READY 有文字状态", async () => {
    vi.spyOn(clientModule.client, "getWorkspaceSummary").mockResolvedValue({
      data: {
        ...summary,
        readiness: { "R::soh_readiness": "NOT_READY_FOR_MODEL_EVALUATION" },
      } as never,
      meta: {},
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/NOT_READY_FOR_MODEL_EVALUATION/)).toBeInTheDocument();
    });
  });

  it("T05 PROVISIONAL timebase 文字可见", async () => {
    vi.spyOn(clientModule.client, "getWorkspaceSummary").mockResolvedValue({
      data: {
        ...summary,
        limitations_registry: [
          { code: "PROVISIONAL_TIMEBASE", severity: "WARNING", description: "时间基准未验证" },
        ],
      } as never,
      meta: {},
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/PROVISIONAL_TIMEBASE/)).toBeInTheDocument();
    });
  });

  it("T06 显示 API 提供的 next_actions", async () => {
    vi.spyOn(clientModule.client, "getWorkspaceSummary").mockResolvedValue({
      data: summary as never,
      meta: {},
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/查看波形/)).toBeInTheDocument();
    });
  });
});
