/**
 * BRW-021R2 — Feature–Target Ranking table (rewritten FeatureRankingTable) tests.
 * Proves: typed error taxonomy, full render flow (alias dedup / forbidden block /
 * TOF provenance / summary), checkbox gating + selection source, TRAIN_ONLY split
 * body, real retry, display sort, a11y, backend-computed detail scatter.
 * @vitest-environment jsdom
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, vi, beforeEach, expect } from "vitest";
import type { ComponentProps } from "react";

const clientMock = { postFeatureTargetRanking: vi.fn() };
vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  client: clientMock,
}));

// Value imports must stay dynamic so the mock factory sees `clientMock` after init
// (vitest hoists vi.mock above static imports — same pattern as feature-workbench.test.tsx).
const { ApiError } = await import("../src/api/client");
const { classifyRankingError, FeatureRankingTable } = await import("../src/components/workbench/FeatureTargetWorkbench");
import type { ApiErrorCode, FeatureRankingEntry, FeatureRankingResponse } from "../src/api/client";
function apiErr(status: number, code: ApiErrorCode, message: string) {
  return new ApiError(status, { error: { code, message, request_id: "REQ-test" } });
}

function rankEntry(code: string, extra: Partial<FeatureRankingEntry> = {}): FeatureRankingEntry {
  return {
    feature_code: code, label_zh: code, label_en: code, family: "amplitude", units: "a.u.",
    pearson_overall: 0.2, spearman_overall: 0.2, pearson_charge: 0.2, pearson_discharge: -0.2,
    spearman_charge: 0.2, spearman_discharge: -0.2, n_valid: 3995, n_missing: 0,
    status: "VALID", direction_status: "SAME_DIRECTION", commit_eligible: true, ...extra,
  };
}

/** Realistic EXPLORATORY response per BRW-021R2 contract. */
function fullResponse(overrides: Partial<FeatureRankingResponse> = {}): FeatureRankingResponse {
  return {
    mode: "EXPLORATORY", target_id: "discharge_capacity_ah",
    ranking: [
      rankEntry("amplitude_a_u", {
        label_zh: "幅值", pearson_overall: 0.06, spearman_overall: 0.06,
        pearson_charge: 0.47, spearman_charge: 0.47, pearson_discharge: -0.56, spearman_discharge: -0.56,
        direction_status: "DIRECTION_DEPENDENT", direction_dependent: true,
        status: "VALID", commit_eligible: true, n_valid: 3995, n_missing: 0,
      }),
      rankEntry("surface_tof_us", { family: "tof", units: "µs", commit_eligible: false }),
      rankEntry("swa_source_movmean5", { exploratory_only: true, legacy_diagnostic: true }),
      rankEntry("entropy_fd", { family: "frequency", status: "NUMERICAL_NAN", pearson_overall: null, spearman_overall: null }),
    ],
    alias_dedup: [{ dropped: "waveform_abs_peak_a_u", kept: "amplitude_a_u", reason: "same underlying series (alias)" }],
    blocked_forbidden: [{ feature_code: "soc_dod_percent", status: "BLOCKED_FORBIDDEN_PREDICTOR", commit_eligible: false, reason: "SOC target leakage" }],
    summary: { aligned_events: 3999, target_eligible_rows: 3995, waveform_valid_frames: 3999 },
    tof_provenance: {
      canonical_method: "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1", tof_definition_version: "V1",
      fs_hz: 5_000_000, fs_verified: true, fs_parameter_set_id: "FS::emb",
      gate_calibration_id: "GC-TOF::embedded", gate_calibration_source: "EMBEDDED", gate_calibration_version: 20,
      surface_gate_id: "SG", bottom_gate_id: "BG", note: "n/a",
      current_gate_calibration_id: "GC-TOF::current", current_gate_calibration_version: 26,
      gate_calibration_window_matches_current: true, waveform_valid_rows: 3995,
    },
    limitations: ["EXPLORATORY_NOT_ML_SAFE", "RANKING_DESCRIBES_ASSOCIATION_ONLY"],
    ...overrides,
  };
}

const envelope = (data: FeatureRankingResponse) => ({ data, meta: {} });

function renderTable(props: ComponentProps<typeof FeatureRankingTable>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}><FeatureRankingTable {...props} /></QueryClientProvider>);
}

const baseProps = {
  batteryId: "CELL_001", experimentId: "EXP_001", targetId: "discharge_capacity_ah",
  features: ["amplitude_a_u", "surface_tof_us", "swa_source_movmean5", "entropy_fd"],
  mode: "EXPLORATORY" as const,
};

beforeEach(() => { vi.resetAllMocks(); });

describe("classifyRankingError — typed failure taxonomy (§22)", () => {
  it("INVALID_SPLIT: split requirements beat generic VALIDATION_ERROR", () => {
    const e = apiErr(400, "VALIDATION_ERROR", "TRAIN_ONLY_ML_SAFE requires split_id and fold_index");
    expect(classifyRankingError(e)).toMatchObject({ kind: "INVALID_SPLIT" });
    expect(classifyRankingError(new Error("invalid split assignments for fold"))).toMatchObject({ kind: "INVALID_SPLIT" });
  });
  it("RELATIONSHIP_ARTIFACT_MISSING: ARTIFACT_NOT_AVAILABLE / not materialized", () => {
    expect(classifyRankingError(apiErr(409, "ARTIFACT_NOT_AVAILABLE", "relationship analysis not materialized"))).toMatchObject({ kind: "RELATIONSHIP_ARTIFACT_MISSING" });
  });
  it("STALE_ANALYSIS: SOURCE_MOVMEAN5 legacy marker", () => {
    expect(classifyRankingError(apiErr(400, "VALIDATION_ERROR", "feature swa_source_movmean5 is diagnostic only"))).toMatchObject({ kind: "STALE_ANALYSIS" });
  });
  it("TARGET_NOT_READY: unknown/not-ready target", () => {
    expect(classifyRankingError(apiErr(404, "NOT_FOUND", "target discharge_capacity_ah is not ready"))).toMatchObject({ kind: "TARGET_NOT_READY" });
    expect(classifyRankingError(new Error("unknown target: nope"))).toMatchObject({ kind: "TARGET_NOT_READY" });
  });
  it("NO_ELIGIBLE_FEATURES: unknown features / VALIDATION_ERROR", () => {
    expect(classifyRankingError(apiErr(400, "VALIDATION_ERROR", "unknown features: entropy_fd"))).toMatchObject({ kind: "NO_ELIGIBLE_FEATURES" });
  });
  it("API_UNAVAILABLE: network failures", () => {
    expect(classifyRankingError(new TypeError("Failed to fetch"))).toMatchObject({ kind: "API_UNAVAILABLE" });
    expect(classifyRankingError(new Error("request timeout"))).toMatchObject({ kind: "API_UNAVAILABLE" });
  });
  it("UNEXPECTED_ERROR: fallback keeps raw detail", () => {
    const r = classifyRankingError(new Error("boom"));
    expect(r.kind).toBe("UNEXPECTED_ERROR");
    expect(r.detail).toContain("boom");
  });
});

describe("FeatureRankingTable render flow (EXPLORATORY)", () => {
  it("runs ranking and renders rows, direction badge, dedup/forbidden notes, provenance and summary", async () => {
    clientMock.postFeatureTargetRanking.mockResolvedValue(envelope(fullResponse()));
    const user = userEvent.setup();
    renderTable(baseProps);
    await user.click(screen.getByTestId("run-ranking-btn"));
    await screen.findByTestId("rank-amplitude_a_u");

    expect(clientMock.postFeatureTargetRanking).toHaveBeenCalledWith("CELL_001", "EXP_001",
      expect.objectContaining({ target_id: "discharge_capacity_ah", mode: "EXPLORATORY" }));
    for (const code of ["amplitude_a_u", "surface_tof_us", "swa_source_movmean5", "entropy_fd"]) {
      expect(screen.getByTestId(`rank-${code}`)).toBeInTheDocument();
    }
    // 方向依赖 badge on the DIRECTION_DEPENDENT entry
    expect(screen.getByTestId("direction-amplitude_a_u")).toHaveTextContent("方向依赖");
    expect(screen.getByTestId("rank-status-entropy_fd")).toHaveTextContent("NUMERICAL_NAN");
    // alias dedup + forbidden block notes
    expect(screen.getByTestId("alias-dedup-note")).toHaveTextContent("waveform_abs_peak_a_u ≡ amplitude_a_u");
    expect(screen.getByTestId("forbidden-blocked")).toHaveTextContent("soc_dod_percent");
    // TOF provenance line carries BOTH artifact and current gate calibration ids
    const prov = screen.getByTestId("ranking-tof-provenance");
    expect(prov).toHaveTextContent("GC-TOF::embedded");
    expect(prov).toHaveTextContent("GC-TOF::current");
    expect(prov).toHaveTextContent("SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1");
    expect(prov).toHaveTextContent("窗口一致");
    // summary: counts + limitations are surfaced
    const summary = screen.getByTestId("ranking-summary");
    expect(summary).toHaveTextContent("3999");
    expect(summary).toHaveTextContent("3995");
    expect(summary).toHaveTextContent("EXPLORATORY_NOT_ML_SAFE");
    expect(screen.getByTestId("ranking-mode-badge")).toHaveTextContent("EXPLORATORY");
  });
});

describe("Selection checkboxes", () => {
  it("commit_eligible=false is disabled; enabled select calls onSelectedChange with EXPLORATORY source", async () => {
    clientMock.postFeatureTargetRanking.mockResolvedValue(envelope(fullResponse()));
    const onSelectedChange = vi.fn();
    const user = userEvent.setup();
    renderTable({ ...baseProps, selected: [], onSelectedChange });
    await user.click(screen.getByTestId("run-ranking-btn"));
    await screen.findByTestId("rank-amplitude_a_u");

    expect(screen.getByTestId("select-surface_tof_us")).toBeDisabled();
    await user.click(screen.getByTestId("select-amplitude_a_u"));
    expect(onSelectedChange).toHaveBeenCalledWith(["amplitude_a_u"], "EXPLORATORY_RELATIONSHIP_RANKING");
  });
});

describe("TRAIN_ONLY_ML_SAFE mode", () => {
  it("sends split_id/fold_index, shows fold badge, selection source is TRAIN_ONLY", async () => {
    clientMock.postFeatureTargetRanking.mockResolvedValue(envelope(fullResponse({
      mode: "TRAIN_ONLY_ML_SAFE", split_id: "SPLIT::g5", fold_index: "fold_2",
    })));
    const onSelectedChange = vi.fn();
    const user = userEvent.setup();
    renderTable({ ...baseProps, mode: "TRAIN_ONLY_ML_SAFE", splitId: "SPLIT::g5", foldIndex: "fold_2", selected: [], onSelectedChange });
    expect(screen.getByTestId("ranking-mode-badge")).toHaveTextContent("TRAIN-ONLY ML-SAFE");
    await user.click(screen.getByTestId("run-ranking-btn"));
    await screen.findByTestId("rank-amplitude_a_u");

    expect(clientMock.postFeatureTargetRanking).toHaveBeenLastCalledWith("CELL_001", "EXP_001",
      expect.objectContaining({ mode: "TRAIN_ONLY_ML_SAFE", split_id: "SPLIT::g5", fold_index: "fold_2" }));
    expect(screen.getByTestId("ranking-fold-badge")).toHaveTextContent("fold_2");
    await user.click(screen.getByTestId("select-amplitude_a_u"));
    expect(onSelectedChange).toHaveBeenCalledWith(["amplitude_a_u"], "TRAIN_ONLY_RELATIONSHIP_RANKING");
  });
});

describe("Error & retry", () => {
  it("failed run shows typed alert; retry issues a real second request and renders the table", async () => {
    clientMock.postFeatureTargetRanking
      .mockRejectedValueOnce(apiErr(409, "ARTIFACT_NOT_AVAILABLE", "relationship analysis not materialized"))
      .mockResolvedValueOnce(envelope(fullResponse()));
    const user = userEvent.setup();
    renderTable(baseProps);
    await user.click(screen.getByTestId("run-ranking-btn"));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("关系分析工件缺失");
    expect(alert).toHaveTextContent("RELATIONSHIP_ARTIFACT_MISSING");
    expect(screen.queryByTestId("rank-amplitude_a_u")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("ranking-retry"));
    await screen.findByTestId("rank-amplitude_a_u");
    expect(clientMock.postFeatureTargetRanking).toHaveBeenCalledTimes(2);
  });
});

describe("Display sort", () => {
  it("ranking-sort switches ordering (|Spearman overall| → |Charge Spearman|)", async () => {
    clientMock.postFeatureTargetRanking.mockResolvedValue(envelope(fullResponse({
      alias_dedup: undefined, blocked_forbidden: undefined, ranking: [
        rankEntry("f_high_overall", { spearman_overall: 0.9, spearman_charge: 0.1 }),
        rankEntry("f_mid", { spearman_overall: 0.5, spearman_charge: 0.8 }),
        rankEntry("f_high_charge", { spearman_overall: 0.2, spearman_charge: 0.95 }),
      ],
    })));
    const user = userEvent.setup();
    const { container } = renderTable({ ...baseProps, features: ["f_high_overall", "f_mid", "f_high_charge"] });
    await user.click(screen.getByTestId("run-ranking-btn"));
    await screen.findByTestId("rank-f_high_overall");

    const order = () => Array.from(container.querySelectorAll("[data-testid^='rank-']"))
      .map(el => el.getAttribute("data-testid"));
    expect(order()).toEqual(["rank-f_high_overall", "rank-f_mid", "rank-f_high_charge"]);

    await user.selectOptions(screen.getByTestId("ranking-sort"), "abs_charge");
    await waitFor(() => {
      expect(order()).toEqual(["rank-f_high_charge", "rank-f_mid", "rank-f_high_overall"]);
    });
  });
});

describe("Accessibility", () => {
  it("column headers, alert role and labeled checkboxes exist", async () => {
    clientMock.postFeatureTargetRanking
      .mockResolvedValueOnce(envelope(fullResponse()))
      .mockRejectedValueOnce(apiErr(500, "INTERNAL_ERROR", "unexpected crash in ranking"));
    const user = userEvent.setup();
    renderTable({ ...baseProps, selected: [], onSelectedChange: vi.fn() });
    await user.click(screen.getByTestId("run-ranking-btn"));
    await screen.findByTestId("rank-amplitude_a_u");

    for (const name of ["Pearson", "Spearman", "Charge ρ", "Discharge ρ", "Direction"]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("checkbox", { name: "选择 amplitude_a_u" })).toBeInTheDocument();

    // error box renders with role=alert (second click fails)
    await user.click(screen.getByTestId("run-ranking-btn"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveAttribute("data-testid", "ranking-error");
  });
});

describe("Relationship detail scatter", () => {
  it("detail click refires request with detail_feature and renders backend scatter", async () => {
    const withDetail = fullResponse({
      detail: {
        feature_code: "amplitude_a_u", target_id: "discharge_capacity_ah",
        scopes: {
          overall: { n: 3995, points: [{ x: 1, y: 2 }, { x: 3, y: 4 }] },
          charge: { n: 1868, points: [{ x: 1, y: 2 }] },
          discharge: { n: 1588, points: [{ x: 3, y: 4 }] },
        },
        excluded_ineligible: 4,
      },
    });
    clientMock.postFeatureTargetRanking.mockImplementation((_b: string, _e: string, body: { detail_feature?: string }) =>
      Promise.resolve(envelope(body.detail_feature ? withDetail : { ...withDetail, detail: null })));
    const user = userEvent.setup();
    renderTable(baseProps);
    await user.click(screen.getByTestId("run-ranking-btn"));
    await screen.findByTestId("rank-amplitude_a_u");
    expect(screen.queryByTestId("relationship-detail")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("detail-amplitude_a_u"));
    const panel = await screen.findByTestId("relationship-detail");
    expect(clientMock.postFeatureTargetRanking).toHaveBeenLastCalledWith("CELL_001", "EXP_001",
      expect.objectContaining({ detail_feature: "amplitude_a_u" }));
    expect(panel).toHaveTextContent("后端计算，前端不重算");
    expect(panel).toHaveTextContent("excluded (ineligible) 4");
    // scope buttons from backend-provided scopes
    const scopeButtons = within(panel).getAllByRole("button");
    for (const scope of ["overall", "charge", "discharge"]) {
      expect(screen.getByTestId(`scatter-scope-${scope}`)).toBeInTheDocument();
    }
    expect(scopeButtons.length).toBeGreaterThanOrEqual(3);
    await user.click(screen.getByTestId("scatter-scope-charge"));
    expect(panel).toHaveTextContent("n=1868");
  });
});
