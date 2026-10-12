/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { clientMock } = vi.hoisted(() => ({
  clientMock: {
    getIntakeSession: vi.fn(),
    uploadIntakeAsset: vi.fn(),
    removeIntakeAsset: vi.fn(),
    createExperiment: vi.fn(),
    createIntakeSession: vi.fn(),
  },
}));

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  client: clientMock,
}));

import { NewExperimentWizardPage } from "../src/pages/NewExperimentWizardPage";

const session = {
  session_id: "session-123",
  battery_id: "CELL_X",
  experiment_id: "EXP_X",
  experiment_composite_id: "CELL_X/EXP_X",
  status: "ASSETS_RECEIVED" as const,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
  assets: [
    {
      intake_asset_id: "asset-e1", session_id: "session-123", role: "ELECTRICAL" as const,
      original_filename: "cycle.xlsx", stored_filename: "cycle.xlsx", size: 10,
      sha256: "a".repeat(64), received_at: "2026-01-01T00:00:00", content_kind: null,
      file_start_time: null, file_end_time: null, anchor_for_asset_id: null,
    },
    {
      intake_asset_id: "asset-u1", session_id: "session-123", role: "ULTRASOUND" as const,
      original_filename: "export.txt", stored_filename: "export.txt", size: 20,
      sha256: "b".repeat(64), received_at: "2026-01-01T00:00:00", content_kind: null,
      file_start_time: null, file_end_time: null, anchor_for_asset_id: null,
    },
  ],
  detections: [], validation: null, commit: null, failure_reason: null, recommended_next_action: null,
};

function renderWizard(initialEntry = "/new/session-123") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes><Route path="/new/:sessionId?" element={<NewExperimentWizardPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("multi-file experiment intake", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clientMock.getIntakeSession.mockResolvedValue({ data: session, meta: {} });
    clientMock.uploadIntakeAsset.mockResolvedValue({
      data: { ...session.assets[0], intake_asset_id: "new-asset" }, meta: {},
    });
  });

  it("records the declared experiment protocol, condition and time bounds", async () => {
    const user = userEvent.setup();
    clientMock.createExperiment.mockResolvedValue({
      data: { battery_id: "CELL_X", experiment_id: "EXP_002" },
      meta: {},
    });
    clientMock.createIntakeSession.mockResolvedValue({ data: session, meta: {} });
    renderWizard("/new");

    await user.type(screen.getByTestId("wiz-battery"), "CELL_X");
    await user.type(screen.getByTestId("wiz-experiment-id"), "EXP_002");
    await user.type(screen.getByTestId("wiz-name"), "25 C discharge");
    await user.type(screen.getByTestId("wiz-protocol"), "CCCV-v2");
    await user.type(screen.getByTestId("wiz-condition-id"), "TEMP_25C_RATE_1C");
    await user.type(screen.getByTestId("wiz-condition-description"), "25 C chamber, 1 C discharge");
    await user.type(screen.getByTestId("wiz-start-time"), "2026-10-07T09:00");
    await user.type(screen.getByTestId("wiz-end-time"), "2026-10-07T11:00");
    await user.click(screen.getByTestId("wiz-continue-info"));

    await waitFor(() => expect(clientMock.createExperiment).toHaveBeenCalledOnce());
    expect(clientMock.createExperiment.mock.calls[0]?.[0]).toMatchObject({
      protocol: "CCCV-v2",
      condition_id: "TEMP_25C_RATE_1C",
      condition_description: "25 C chamber, 1 C discharge",
      start_time: "2026-10-07T09:00",
      end_time: "2026-10-07T11:00",
    });
  });

  it("restores the asset step, uploads each selected file and keeps M2K binding explicit", async () => {
    const user = userEvent.setup();
    renderWizard();

    const electrical = await screen.findByTestId("upload-electrical") as HTMLInputElement;
    const ultrasound = screen.getByTestId("upload-ultrasound") as HTMLInputElement;
    expect(electrical.multiple).toBe(true);
    expect(ultrasound.multiple).toBe(true);
    expect(screen.getByTestId("m2k-anchor-target")).toBeInTheDocument();

    await user.upload(electrical, [new File(["one"], "same.xlsx"), new File(["two"], "same.xlsx")]);
    await waitFor(() => expect(clientMock.uploadIntakeAsset).toHaveBeenCalledTimes(2));
    expect(clientMock.uploadIntakeAsset.mock.calls.map((call) => call[1])).toEqual(["ELECTRICAL", "ELECTRICAL"]);

    const anchorSelect = screen.getByTestId("m2k-anchor-target");
    await user.selectOptions(anchorSelect, "asset-u1");
    await user.upload(screen.getByTestId("upload-m2k-evidence"), new File(["xml"], "config.xml"));
    await waitFor(() => expect(clientMock.uploadIntakeAsset).toHaveBeenCalledTimes(3));
    expect(clientMock.uploadIntakeAsset.mock.calls[2]?.[1]).toBe("EXPERIMENT_METADATA");
    expect(clientMock.uploadIntakeAsset.mock.calls[2]?.[4]).toBe("asset-u1");
  });

  it("removes only a staged asset and refreshes the visible asset list", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    clientMock.removeIntakeAsset.mockResolvedValue({
      data: { ...session, assets: [session.assets[0]] }, meta: {},
    });
    renderWizard();

    await user.click(await screen.findByTestId("remove-staged-asset-asset-u1"));

    expect(clientMock.removeIntakeAsset).toHaveBeenCalledWith("session-123", "asset-u1");
    await waitFor(() => expect(screen.queryByText("export.txt", { exact: false })).not.toBeInTheDocument());
    expect(screen.getByTestId("uploaded-list").textContent).toContain("cycle.xlsx");
  });
});
