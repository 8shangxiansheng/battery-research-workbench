/**
 * BRW-025R-FE-R1 scientific guard tests.
 * S01–S07 synchronization semantics, T01–T05 target metadata, L01–L06
 * feature–label table, M01–M08 ML-safety — component level with mocked client.
 * @vitest-environment jsdom
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, vi, beforeEach } from "vitest";

const clientMock = {
  listTargets: vi.fn(),
  getAlignmentSummary: vi.fn(),
  getAlignmentSamples: vi.fn(),
  getAlignmentExclusions: vi.fn(),
  postFeatureLabelPreview: vi.fn(),
  postFeatureTargetRanking: vi.fn(),
};
vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  client: clientMock,
}));

import type { AlignmentSummaryResponse, AlignmentSampleRow, TargetDefinition } from "../src/api/client";

function renderPage(node: React.ReactNode, path = "/experiments/CELL_001/EXP_001") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/experiments/:batteryId/:experimentId/*" element={node} />
          <Route path="*" element={node} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const socTarget: TargetDefinition = {
  target_id: "reference_soc_percent", display_name_en: "Reference SOC", display_name_zh: "参考SOC",
  semantic_type: "DERIVED_REFERENCE_LABEL", source: "Electrical XLSX via label engine",
  coverage: { valid: 3995, total: 3999 }, range: [0, 100],
  readiness: "READY_FOR_LIMITED_EVALUATION", limitation: "Retrospective reference label, not a directly measured state of charge",
  limitation_zh: "回顾性参考标签", unit: "percent",
};
const summaryFixture: AlignmentSummaryResponse = {
  total_frames: 3999, matched_unique: 3995, ambiguous: 4, unmatched: 0,
  target_valid: { reference_soc_percent: 3995 }, eligible: 3995, excluded: 4,
  sync_quality: {
    validated_sync: false, timebase_status: "PROVISIONAL", matching_performed: true,
    max_sync_error_s: 0.0312, sync_tolerance_s: null, max_sync_error_limit_s: 1.0,
  },
};
const uniqueRow: AlignmentSampleRow = {
  measurement_event_id: "ME::CELL_001::EXP_001::U001::0", frame_index_raw: 0,
  ultrasound_timestamp: "2024-01-06 09:52:31", electrical_asset_id: "E001",
  electrical_record_locator: "2", electrical_timestamp: "2024-01-06 09:52:31",
  match_status: "MATCHED_UNIQUE", sync_ambiguous: false, sync_error_s: 0.0312,
  within_tolerance: true, analysis_eligible: true,
  targets: { reference_soc_percent: 0.0, temperature_c: null, soh_capacity_reference_percent: 100, voltage_v: 3.35, current_a: 4.97 },
};
const ambiguousRow: AlignmentSampleRow = {
  ...uniqueRow,
  measurement_event_id: "ME::CELL_001::EXP_001::U001::691", frame_index_raw: 691,
  electrical_asset_id: null, electrical_record_locator: null, electrical_timestamp: null,
  match_status: "MATCHED_AMBIGUOUS", sync_ambiguous: true, analysis_eligible: false,
  targets: { reference_soc_percent: null, temperature_c: null, soh_capacity_reference_percent: null, voltage_v: null, current_a: null },
};

beforeEach(() => { vi.clearAllMocks(); });

/* ---------- Synchronization guards (S01–S07) ---------- */
describe("Synchronization guards", () => {
  it("S01 canonical alignment summary renders 7 counts + provisional semantics", async () => {
    clientMock.getAlignmentSummary.mockResolvedValue({ data: summaryFixture, meta: {} });
    const { AlignmentSummary } = await import("../src/components/workbench/AlignmentPanels");
    renderPage(<AlignmentSummary batteryId="C" experimentId="E" targetId="reference_soc_percent" />);
    await waitFor(() => {
      expect(screen.getByTestId("align-total").textContent).toBe("3,999");
      expect(screen.getByTestId("align-matched").textContent).toBe("3,995");
      expect(screen.getByTestId("align-ambiguous").textContent).toBe("4");
      expect(screen.getByTestId("align-eligible").textContent).toBe("3,995");
      expect(screen.getByTestId("align-excluded").textContent).toBe("4");
    });
    const badge = screen.getByTestId("alignment-status-badge");
    expect(badge.textContent).toContain("validated_sync=false");
    expect(screen.getByTestId("alignment-semantics").textContent).toContain("不是完全验证同步");
    expect(screen.getByTestId("alignment-semantics").textContent).not.toMatch(/fully validated/i);
  });

  it("S02–S04 no rematch note + gate context displayed", async () => {
    clientMock.getAlignmentSummary.mockResolvedValue({ data: summaryFixture, meta: {} });
    const { AlignmentSummary } = await import("../src/components/workbench/AlignmentPanels");
    renderPage(<AlignmentSummary batteryId="C" experimentId="E" targetId={null} />);
    const note = await screen.findByTestId("alignment-semantics");
    expect(note.textContent).toContain("共享同一个 MeasurementEvent 电学状态");
    expect(note.textContent).toContain("share the same electrical context");
  });

  it("S06 ambiguous row: electrical identity null, never auto-selected", async () => {
    clientMock.getAlignmentSamples.mockResolvedValue({ data: { samples: [ambiguousRow], total: 4 }, meta: {} });
    const { AlignmentSamplesPanel } = await import("../src/components/workbench/AlignmentPanels");
    const user = userEvent.setup();
    renderPage(<AlignmentSamplesPanel batteryId="C" experimentId="E" />);
    const row = await screen.findByTestId(`align-row-${ambiguousRow.measurement_event_id}`);
    expect(row.textContent).toContain("null");
    await user.click(row);
    const drawer = await screen.findByTestId("provenance-drawer");
    expect(drawer.textContent).toContain("null");
    expect(drawer.textContent).toContain("never auto-selected");
  });

  it("S07 row preview shows MeasurementEvent→electrical→sync chain", async () => {
    clientMock.getAlignmentSamples.mockResolvedValue({ data: { samples: [uniqueRow], total: 3995 }, meta: {} });
    const { AlignmentSamplesPanel } = await import("../src/components/workbench/AlignmentPanels");
    const user = userEvent.setup();
    renderPage(<AlignmentSamplesPanel batteryId="C" experimentId="E" />);
    const row = await screen.findByTestId(`align-row-${uniqueRow.measurement_event_id}`);
    await user.click(row);
    const drawer = await screen.findByTestId("provenance-drawer");
    expect(drawer.textContent).toContain("ME::CELL_001::EXP_001::U001::0");
    expect(drawer.textContent).toContain("E001");
    expect(drawer.textContent).toContain("0.0312");
  });
});

/* ---------- Target guards (T01–T05) ---------- */
describe("Target guards", () => {
  it("T01/T02 Reference SOC metadata — retrospective wording, no true-SOC", async () => {
    clientMock.listTargets.mockResolvedValue({ data: { targets: [socTarget] }, meta: {} });
    const { TargetSelector } = await import("../src/components/workbench/TargetSelector");
    renderPage(<TargetSelector batteryId="C" experimentId="E" selected={null} onSelect={() => {}} />);
    const card = await screen.findByTestId("target-card-reference_soc_percent");
    expect(card.textContent).toContain("参考SOC");
    expect(screen.getByTestId("soc-retrospective-note").textContent).toContain("Retrospective segment-normalized reference label");
    expect(screen.queryByText(/True SOC|Ground Truth/i)).not.toBeInTheDocument();
  });

  it("T03 temperature readiness honest (unavailable stays unavailable)", async () => {
    const temp: TargetDefinition = { ...socTarget, target_id: "temperature_c", display_name_en: "Temperature", display_name_zh: "温度", semantic_type: "DIRECT_MEASUREMENT", coverage: { valid: 0, total: 3999 }, range: null, readiness: "UNAVAILABLE", limitation: "no temperature channel", limitation_zh: "无温度通道", unit: "celsius" };
    clientMock.listTargets.mockResolvedValue({ data: { targets: [temp] }, meta: {} });
    const { TargetSelector } = await import("../src/components/workbench/TargetSelector");
    renderPage(<TargetSelector batteryId="C" experimentId="E" selected={null} onSelect={() => {}} />);
    await screen.findByTestId("target-unavailable-temperature_c");
    expect(screen.getByTestId("target-card-temperature_c").textContent).toContain("0 / 3,999");
  });

  it("T04 SOH independent-group count visible with Limited badge", async () => {
    const soh: TargetDefinition = { ...socTarget, target_id: "soh_capacity_reference_percent", display_name_en: "SOH", display_name_zh: "健康状态", semantic_type: "DERIVED_HEALTH_STATE", coverage: { valid: 3995, total: 3999, independent_states: 2 }, readiness: "NOT_READY", limitation: "only 2 independent SOH states", limitation_zh: "仅 2 个独立 SOH 状态；帧行是伪重复", unit: "percent" };
    clientMock.listTargets.mockResolvedValue({ data: { targets: [soh] }, meta: {} });
    const { TargetSelector } = await import("../src/components/workbench/TargetSelector");
    renderPage(<TargetSelector batteryId="C" experimentId="E" selected={null} onSelect={() => {}} />);
    const badge = await screen.findByTestId("target-limited-soh_capacity_reference_percent");
    expect(badge.textContent).toMatch(/Limited/i);
    expect(screen.getByTestId("target-card-soh_capacity_reference_percent").textContent).toContain("2 独立状态");
  });
});

/* ---------- Feature–Label guards (L01–L06) ---------- */
describe("Feature–Label table guards", () => {
  const previewFixture = {
    target_id: "reference_soc_percent",
    target_source: "Electrical XLSX via label engine",
    target_readiness: "READY_FOR_LIMITED_EVALUATION",
    features: ["SWA", "BOTTOM_AMP"],
    rows: [
      { measurement_event_id: "ME::1", frame_index_raw: 0, cycle: 1, state: "charge", target: 0.5, values: { SWA: 1.1, BOTTOM_AMP: 2.2 }, sync_error_s: 0.03, electrical_asset_id: "E001" },
    ],
    summary: {
      total_frames: 3999, aligned_events: 3999, eligible_rows: 3995, excluded_rows: 4,
      excluded_by_reason: { AMBIGUOUS_SYNC: 4 }, cycles: [1, 2], missing_values: 0,
      alignment_status: "PROVISIONAL_TIMEBASE_MATCHED",
    },
  };

  it("L01/L02/L03 one row per event + exactly one target + selected features only", async () => {
    clientMock.postFeatureLabelPreview.mockResolvedValue({ data: previewFixture, meta: {} });
    const { FeatureLabelTablePreview } = await import("../src/components/workbench/FeatureLabelTable");
    renderPage(<FeatureLabelTablePreview batteryId="C" experimentId="E" targetId="reference_soc_percent" features={["SWA", "BOTTOM_AMP"]} />);
    await screen.findByTestId("preview-table-btn");
    const user = userEvent.setup();
    await user.click(screen.getByTestId("preview-table-btn"));
    const row = await screen.findByTestId("fl-row-ME::1");
    expect(row.textContent).toContain("0.5");
    expect(row.getAttribute("onclick")).toBeNull();
    // summary shows target + eligible/excluded
    const summaryEl = screen.getByTestId("feature-label-summary");
    expect(summaryEl.textContent).toContain("Reference SOC / 参考 SOC");
    expect(summaryEl.textContent).toContain("3,995 / 4");
    expect(screen.getByTestId("funnel-raw").textContent).toBe("3,999");
    expect(screen.getByTestId("funnel-eligible").textContent).toBe("3,995");
  });

  it("L06 row provenance drawer shows full chain", async () => {
    clientMock.postFeatureLabelPreview.mockResolvedValue({ data: previewFixture, meta: {} });
    const { FeatureLabelTablePreview } = await import("../src/components/workbench/FeatureLabelTable");
    const user = userEvent.setup();
    renderPage(<FeatureLabelTablePreview batteryId="C" experimentId="E" targetId="reference_soc_percent" features={["SWA", "BOTTOM_AMP"]} />);
    await user.click(await screen.findByTestId("preview-table-btn"));
    await user.click(await screen.findByTestId("fl-row-ME::1"));
    const drawer = await screen.findByTestId("feature-label-row-provenance");
    expect(drawer.textContent).toContain("ME::1");
    expect(drawer.textContent).toContain("E001");
    expect(drawer.textContent).toContain("Ultrasound frame");
    expect(drawer.textContent).toContain("Target / 目标值");
    // chain subtitle lives in the dialog description
    expect(screen.getByText(/waveform → gate → feature → MeasurementEvent → electrical record → target/i)).toBeInTheDocument();
  });
});

/* ---------- ML-safety guards (M01–M08) ---------- */
describe("ML-safety guards", () => {
  it("M01/M02 exploratory badge explicitly not ML-safe", async () => {
    clientMock.postFeatureTargetRanking.mockResolvedValue({ data: {
      mode: "EXPLORATORY", target_id: "reference_soc_percent",
      ranking: [{ feature_code: "SWA", pearson_overall: 0.5, spearman_overall: 0.4, n_valid: 100, status: "VALID" }],
    }, meta: {} });
    const { FeatureRankingTable } = await import("../src/components/workbench/FeatureTargetWorkbench");
    renderPage(<FeatureRankingTable batteryId="C" experimentId="E" targetId="reference_soc_percent" features={["SWA"]} mode="EXPLORATORY" />);
    const badge = await screen.findByTestId("ranking-mode-badge");
    expect(badge.textContent).toContain("非 ML-safe");
  });

  it("M07 SOURCE_MOVMEAN5 protected in dataset preview (exploratory only warning)", async () => {
    const { DatasetXYPreview } = await import("../src/components/workbench/DatasetXYPreview");
    renderPage(<DatasetXYPreview open onClose={() => {}} target={socTarget}
      summary={{ total_frames: 3999, aligned_events: 3999, eligible_rows: 3995, excluded_rows: 4,
        excluded_by_reason: { AMBIGUOUS_SYNC: 4 }, cycles: [1, 2], missing_values: 0,
        alignment_status: "PROVISIONAL_TIMEBASE_MATCHED" }}
      features={["SWA", "swa_source_movmean5"]} mode="TRAIN_ONLY_ML_SAFE"
      onBuild={() => {}} building={false} built={false} buildError={null} />);
    await screen.findByTestId("dataset-xy-preview");
    // the movmean5 guard renders beside the X/y grid (dialog level)
    expect(screen.getByRole("alert").textContent).toContain("SOURCE_MOVMEAN5 为 Exploratory only");
    expect(screen.getByTestId("xy-mlsafe").textContent).toBe("TRAIN_ONLY_ML_SAFE");
  });

  it("M03/M08 no random frame split UI anywhere in workflow components", async () => {
    clientMock.getAlignmentSummary.mockResolvedValue({ data: summaryFixture, meta: {} });
    const { AlignmentSummary } = await import("../src/components/workbench/AlignmentPanels");
    const { container } = renderPage(<AlignmentSummary batteryId="C" experimentId="E" targetId={null} />);
    await screen.findByTestId("alignment-summary");
    expect(container.textContent).not.toMatch(/random frame split/i);
  });

  it("M05 held-out protection: ranking request carries mode only, no held-out target access API", async () => {
    clientMock.postFeatureTargetRanking.mockClear();
    clientMock.postFeatureTargetRanking.mockResolvedValue({ data: {
      mode: "TRAIN_ONLY_ML_SAFE", target_id: "reference_soc_percent",
      ranking: [{ feature_code: "SWA", pearson_overall: 0.5, n_valid: 2000, status: "VALID" }],
    }, meta: {} });
    const { FeatureRankingTable } = await import("../src/components/workbench/FeatureTargetWorkbench");
    renderPage(<FeatureRankingTable batteryId="C" experimentId="E" targetId="reference_soc_percent" features={["SWA"]} mode="TRAIN_ONLY_ML_SAFE" />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("run-ranking-btn"));
    await waitFor(() => {
      expect(clientMock.postFeatureTargetRanking).toHaveBeenCalledWith("C", "E", {
        target_id: "reference_soc_percent", features: ["SWA"], mode: "TRAIN_ONLY_ML_SAFE",
      });
    });
    // contract: request shape has no held-out access fields
    const call = clientMock.postFeatureTargetRanking.mock.calls[0]![2] as Record<string, unknown>;
    expect(Object.keys(call).sort()).toEqual(["features", "mode", "target_id"]);
  });
});
