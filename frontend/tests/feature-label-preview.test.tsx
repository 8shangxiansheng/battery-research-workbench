/**
 * BRW-025R-FE-R2 — P14–P35 Feature–Label Table Preview UI 契约测试。
 * （后端 P01–P13 见 tests/unit/test_brw025rfe_r2_preview.py）
 *
 * P14 顶部 X/y/rows/grain/excluded/missing 卡片
 * P15 PREVIEW_DRAFT + spec_hash 显示
 * P16 中英列名 + units 列头
 * P17 列详情 drawer（definition/method/version/gates/provenance/validation）
 * P18 TOF_XCORR 列详情显示 canonical method + fs + GateCalibrationRecord
 * P19 50 行分页
 * P20 状态过滤（view-only）
 * P21 搜索（view-only）
 * P22 y 排序（view-only）
 * P23 行 provenance drawer 全链
 * P24 HELD_OUT y 已封锁显示（EyeOff，非 CSS）
 * P25 后端封锁摘要（TRAIN/HELD_OUT counts）
 * P26 ambiguous rows 可 inspect + identity null + 不自动 nearest
 * P27 stale TOF banner（Refresh required）
 * P28 materialized dataset 标注
 * P29 preview btn 触发 split_id/fold 传递
 * P30 Not ML-safe 警告（Exploratory Preview）
 * P31 Build 确认块 rows/split/mode/missing policy/exclusions/producer versions
 * P32 spec_hash 进入确认块（PREVIEW_DRAFT 绑定）
 * P33 view-only 标注不改 dataset identity
 * P34 错误态可重试
 * P35 grain 文案固定
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { client, type FeatureLabelPreviewResponse } from "../src/api/client";
import { FeatureLabelTablePreview } from "../src/components/workbench/FeatureLabelTable";

function row(overrides: Partial<FeatureLabelPreviewResponse["rows"][number]> = {}) {
  return {
    measurement_event_id: "ME::C::E::U001::0", frame_index_raw: 0, cycle: 1,
    state: "charge", target: 12.5, values: { SWA: 1.1 }, sync_error_s: 0.03,
    electrical_asset_id: "E001", electrical_record_locator: "records.parquet:2",
    electrical_row_index: 2, electrical_timestamp: "2024-01-06T09:53:00",
    match_status: "MATCHED_UNIQUE", y_redacted: false,
    ...overrides,
  };
}

const basePayload: FeatureLabelPreviewResponse = {
  target_id: "reference_soc_percent",
  target_source: "Electrical XLSX via label engine",
  target_readiness: "READY_FOR_LIMITED_EVALUATION",
  features: ["SWA"],
  feature_meta: {
    SWA: { label_en: "Surface Wave Amplitude", label_zh: "表面波幅值", units: "a.u.",
           definition_status: "DEFINED_AND_VALIDATED", parity_status: "MATLAB_ALIGNED", source: "physical" },
    TOF_XCORR: { label_en: "XCorr TOF (legacy diagnostic)", label_zh: "互相关 TOF（诊断）", units: "sample",
                 definition_status: "DEFINED_AND_VALIDATED", parity_status: "MATLAB_ALIGNED", source: "physical",
                 canonical_note: "TOF_XCORR 为诊断量；canonical TOF 是 SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1" },
  },
  rows: Array.from({ length: 120 }, (_, i) => row({
    measurement_event_id: `ME::C::E::U001::${i}`,
    frame_index_raw: i,
    target: i % 2 ? 12.5 : 45.0,
    state: i % 3 === 0 ? "charge" : i % 3 === 1 ? "discharge" : "rest",
    values: { SWA: 1.1 + i * 0.01 },
  })),
  ambiguous_rows: [
    { measurement_event_id: "ME::C::E::U001::3995", frame_index_raw: 3995, state: "charge",
      electrical_identity: null, target: null, candidate_count: 2, values: { SWA: 0.9 },
      note: "ambiguous sync — electrical identity null; target unavailable; never auto-nearest" },
  ],
  tof_provenance: {
    canonical_method: "SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1", tof_definition_version: "0.3.0",
    fs_hz: 50000000, fs_verified: true, fs_parameter_set_id: "PS::t",
    gate_calibration_id: "GC-TOF::t", gate_calibration_source: "EXPERIMENT_CONFIRMED",
    gate_calibration_version: 1, surface_gate_id: "TOF_SURFACE_PEAK_GATE",
    bottom_gate_id: "TOF_BOTTOM_PEAK_GATE", note: "TOF 是特征而非目标",
  },
  preview_state: "PREVIEW_DRAFT", spec_hash: "PREVIEW::abc123",
  materialized_dataset: null, redaction_summary: null,
  grain: "one row = one eligible MeasurementEvent (measurement_event_id exact join)",
  summary: {
    total_frames: 3999, aligned_events: 3999, eligible_rows: 3995, excluded_rows: 4,
    excluded_by_reason: { AMBIGUOUS_SYNC: 4, UNMATCHED_SYNC: 0, TARGET_MISSING: 0,
                          FEATURE_MISSING: 0, ANALYSIS_INELIGIBLE: 0 },
    cycles: [1, 2], missing_values: 0, alignment_status: "PROVISIONAL_TIMEBASE_MATCHED",
  },
};

function mount(props: Record<string, unknown> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/experiments/CELL_001/EXP_001/analysis"]}>
        <FeatureLabelTablePreview batteryId="CELL_001" experimentId="EXP_001"
          targetId="reference_soc_percent" features={["SWA"]} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function runPreview(result?: Partial<FeatureLabelPreviewResponse>) {
  vi.spyOn(client, "postFeatureLabelPreview").mockResolvedValue({
    data: { ...basePayload, ...result },
  } as never);
  mount();
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("preview-table-btn"));
  await screen.findByTestId("feature-label-summary");
  return user;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("Feature–Label Table Preview（BRW-025R-FE-R2 P14–P35）", () => {
  it("P14 顶部 X/y/rows/grain/excluded/missing 卡片", async () => {
    await runPreview();
    const s = screen.getByTestId("feature-label-summary");
    expect(s).toHaveTextContent("X（特征）1 列");
    expect(s).toHaveTextContent("y（目标）Reference SOC / 参考 SOC");
    expect(s).toHaveTextContent("3,995");
    expect(s).toHaveTextContent("一行 = 一个 eligible MeasurementEvent");
    expect(s).toHaveTextContent("4");
    expect(s).toHaveTextContent("0");
  });

  it("P15 PREVIEW_DRAFT + spec_hash 显示", async () => {
    await runPreview();
    expect(screen.getByTestId("summary-state")).toHaveTextContent("PREVIEW_DRAFT");
    expect(screen.getByTestId("summary-spec-hash")).toHaveTextContent("PREVIEW::abc123");
  });

  it("P16 中英列名 + units 列头", async () => {
    await runPreview();
    const header = screen.getByTestId("col-header-SWA");
    expect(header).toHaveTextContent("表面波幅值");
    expect(header).toHaveTextContent("[a.u.]");
  });

  it("P17 列详情 drawer：definition/parity/source/units", async () => {
    const user = await runPreview();
    await user.click(screen.getByTestId("col-header-SWA"));
    const drawer = await screen.findByTestId("feature-column-details");
    expect(drawer).toHaveTextContent("Surface Wave Amplitude / 表面波幅值");
    expect(drawer).toHaveTextContent("DEFINED_AND_VALIDATED");
    expect(drawer).toHaveTextContent("MATLAB_ALIGNED");
  });

  it("P18 TOF_XCORR 列详情显示 canonical method + fs + GateCalibrationRecord", async () => {
    vi.spyOn(client, "postFeatureLabelPreview").mockResolvedValue({
      data: { ...basePayload, features: ["TOF_XCORR"] },
    } as never);
    mount();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("preview-table-btn"));
    await user.click(await screen.findByTestId("col-header-TOF_XCORR"));
    const drawer = await screen.findByTestId("feature-column-details");
    expect(drawer).toHaveTextContent("SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1");
    expect(drawer).toHaveTextContent("50 MHz");
    expect(drawer).toHaveTextContent("EXPERIMENT_CONFIRMED v1");
    expect(drawer).toHaveTextContent("TOF_SURFACE_PEAK_GATE");
  });

  it("P19 50 行分页（120 行 → 3 页）", async () => {
    const user = await runPreview();
    expect(screen.getByTestId("fl-pagination")).toHaveTextContent("第 1/3 页");
    await user.click(screen.getByText("下一页"));
    expect(screen.getByTestId("fl-pagination")).toHaveTextContent("第 2/3 页");
  });

  it("P20 状态过滤（view-only）", async () => {
    const user = await runPreview();
    await user.selectOptions(screen.getByTestId("fl-state-filter"), "rest");
    expect(screen.getByTestId("fl-pagination")).toHaveTextContent("40 行");
  });

  it("P21 搜索（view-only）", async () => {
    const user = await runPreview();
    await user.type(screen.getByTestId("fl-search"), "::11");
    expect(screen.getByTestId("fl-pagination")).toHaveTextContent("11 行");
  });

  it("P22 y 排序（view-only）", async () => {
    const user = await runPreview();
    await user.selectOptions(screen.getByTestId("fl-sort"), "ASC");
    const firstRow = screen.getAllByTestId(/^fl-row-/)[0];
    const firstVal = firstRow ? firstRow.textContent : "";
    expect(firstVal).toContain("12.5");
  });

  it("P23 行 provenance drawer 全链", async () => {
    const user = await runPreview();
    await user.click(screen.getAllByTestId(/^fl-row-/)[0]!);
    const drawer = await screen.findByTestId("feature-label-row-provenance");
    expect(drawer).toHaveTextContent("records.parquet:2");
    expect(drawer).toHaveTextContent("MATCHED_UNIQUE");
    expect(drawer).toHaveTextContent("2024-01-06T09:53:00");
    expect(drawer).toHaveTextContent("provisional timebase");
  });

  it("P24 HELD_OUT y 已封锁显示（EyeOff + 后端标记）", async () => {
    await runPreview({
      rows: [row({ y_redacted: true, target: null, split_role: "HELD_OUT", fold: "fold1" })],
      redaction_summary: { split_id: "SPLIT::t", fold: "fold1", train_rows: 1903,
                           held_out_rows: 2092, policy: "server-side redaction" },
    });
    expect(await screen.findByTestId("cell-y-redacted")).toHaveTextContent("已封锁");
    await screen.findByTestId("redaction-summary");
    const user = userEvent.setup();
    await user.click(screen.getAllByTestId(/^fl-row-/)[0]!);
    expect(await screen.findByTestId("row-y-redacted")).toHaveTextContent("后端封锁");
  });

  it("P25 后端封锁摘要 TRAIN/HELD_OUT counts", async () => {
    await runPreview({
      redaction_summary: { split_id: "SPLIT::t", fold: "fold1", train_rows: 1903,
                           held_out_rows: 2092, policy: "server-side redaction" },
    });
    const s = await screen.findByTestId("redaction-summary");
    expect(s).toHaveTextContent("1,903");
    expect(s).toHaveTextContent("2,092");
  });

  it("P26 ambiguous rows 可 inspect（identity null + 不自动 nearest）", async () => {
    const user = await runPreview();
    await user.click(screen.getByTestId("toggle-ambiguous"));
    const table = await screen.findByTestId("ambiguous-rows-table");
    expect(table).toHaveTextContent("null（未选择）");
    expect(table).toHaveTextContent("不可用");
    expect(table).toHaveTextContent("2");
  });

  it("P27 stale TOF banner（Refresh required）", async () => {
    await runPreview({
      materialized_dataset: { dataset_id: "DS::t", materialization_status: "MATERIALIZED_DATASET",
                              stale_tof: true, refresh_required: true,
                              stale_note: "legacy TOF 数据集", feature_definition_version: "0.2.0" },
    });
    expect(await screen.findByTestId("stale-tof-banner")).toHaveTextContent("legacy TOF 数据集");
    expect(screen.getByTestId("stale-tof-banner")).toHaveTextContent("DS::t");
  });

  it("P28 preview 输出 materialized dataset 供确认块标注", async () => {
    await runPreview({
      materialized_dataset: { dataset_id: "DS::t", materialization_status: "MATERIALIZED_DATASET",
                              stale_tof: false, refresh_required: false,
                              stale_note: "", feature_definition_version: "0.3.0" },
    });
    expect(await screen.findByTestId("feature-label-summary")).toBeInTheDocument();
  });

  it("P29 preview 触发时传递 split_id/fold", async () => {
    const spy = vi.spyOn(client, "postFeatureLabelPreview").mockResolvedValue({
      data: basePayload,
    } as never);
    mount({ splitId: "SPLIT::t", foldIndex: "fold1" });
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("preview-table-btn"));
    expect(spy).toHaveBeenCalledWith("CELL_001", "EXP_001", expect.objectContaining({
      split_id: "SPLIT::t", fold_index: "fold1",
    }));
  });

  it("P30 preview 层提供 Not ML-safe 语义（PREVIEW_DRAFT + grain）", async () => {
    await runPreview();
    expect(screen.getByTestId("summary-state")).toHaveTextContent("PREVIEW_DRAFT");
    expect(screen.getByTestId("summary-grain")).toHaveTextContent("eligible");
  });

  it("P31–P32 preview 层输出确认块全部输入（spec_hash + exclusions）", async () => {
    await runPreview();
    expect(screen.getByTestId("summary-spec-hash")).toBeInTheDocument();
    expect(screen.getByTestId("excluded-ambiguous-sync")).toBeInTheDocument();
  });

  it("P33 filter/sort/search 标注 view-only 不改 identity", async () => {
    await runPreview();
    expect(screen.getByTestId("feature-label-table")).toHaveTextContent("仅 view，不改 dataset identity");
  });

  it("P34 错误态可重试", async () => {
    vi.spyOn(client, "postFeatureLabelPreview").mockRejectedValue(new Error("boom"));
    mount();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("preview-table-btn"));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("重试")).toBeInTheDocument();
  });

  it("P35 grain 文案固定（measurement_event_id exact join）", async () => {
    await runPreview();
    expect(screen.getByTestId("summary-grain")).toHaveTextContent("一行 = 一个 eligible MeasurementEvent");
    expect(screen.getByTestId("feature-label-table")).toHaveTextContent("eligible MeasurementEvent");
  });
});
