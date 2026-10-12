import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TargetSourcePreflight } from "../src/components/workbench/TargetSourcePreflight";
import { client, type TargetDefinition } from "../src/api/client";

vi.mock("../src/api/client", () => ({
  client: {
    validateTargetSourceEvidence: vi.fn(),
  },
}));

const provenance = {
  target_grain: "MEASUREMENT_EVENT" as const,
  independent_unit: "BATTERY" as const,
  method_id: "PROTOCOL_ANCHORED_SEGMENT_NORMALIZED",
  method_version: "0.2.0",
  definition: "Reference SOC derived from charge throughput.",
  source_assets: [{ asset_id: "E001", source_reference: "batteries/CELL_A/EXP_A/electrical/source.xlsx", sha256: "a".repeat(64) }],
  uncertainty: { status: "UNKNOWN" as const, reason: "No validated uncertainty estimate." },
};

const target: TargetDefinition = {
  target_id: "reference_soc_percent",
  display_name_en: "Reference SOC",
  display_name_zh: "参考 SOC",
  semantic_type: "DERIVED_REFERENCE_LABEL" as const,
  source: "electrical throughput",
  coverage: { valid: 10, total: 10 },
  range: [0, 100] as [number, number],
  readiness: "READY",
  limitation: null,
  unit: "percent",
  provenance,
};

function renderPanel(features: string[], targetValue = target) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>
    <TargetSourcePreflight batteryId="CELL_A" experimentId="EXP_A" target={targetValue} features={features} />
  </QueryClientProvider>);
}

describe("TargetSourcePreflight", () => {
  beforeEach(() => vi.clearAllMocks());

  it("submits selected target provenance and selected feature locators", async () => {
    vi.mocked(client.validateTargetSourceEvidence).mockResolvedValue({
      data: {
        status: "SOURCE_EVIDENCE_VERIFIED",
        target_id: "reference_soc_percent",
        verified_sources: [{ asset_id: "E001", verified: true, sha256: "a".repeat(64), parser_provenance: "VERIFIED" }],
        source_integrity: "VERIFIED",
        label_source_semantics: "NOT_ASSESSED",
        target_readiness: "NOT_ASSESSED",
        feature_availability: "NOT_ASSESSED",
        materialization_enabled: false,
      },
      meta: {},
    });

    renderPanel(["tof_us@GATE_01", "SWA"]);

    fireEvent.click(screen.getByRole("button", { name: "核验目标来源文件" }));

    await waitFor(() => expect(client.validateTargetSourceEvidence).toHaveBeenCalledWith({
      battery_ids: ["CELL_A"],
      experiment_ids: ["EXP_A"],
      target_id: "reference_soc_percent",
      target_grain: "MEASUREMENT_EVENT",
      feature_locators: [{ feature_name: "tof_us", gate_id: "GATE_01" }, { feature_name: "SWA" }],
      label_provenance: {
        semantic_type: "DERIVED_REFERENCE_LABEL",
        method_id: "PROTOCOL_ANCHORED_SEGMENT_NORMALIZED",
        method_version: "0.2.0",
        definition: "Reference SOC derived from charge throughput.",
        unit: "percent",
        independent_unit: "BATTERY",
        source_references: provenance.source_assets,
        uncertainty: provenance.uncertainty,
      },
    }));
    expect(await screen.findByTestId("target-source-integrity-status")).toHaveTextContent("文件完整性已核验");
    expect(screen.getByTestId("target-source-semantics-status")).toHaveTextContent("未评估");
    expect(screen.getByTestId("target-source-materialization-status")).toHaveTextContent("未创建数据集");
  });

  it("keeps future target labels blocked when provenance is incomplete", () => {
    renderPanel(["SWA"], { ...target, provenance: undefined });
    expect(screen.getByRole("button", { name: "核验目标来源文件" })).toBeDisabled();
    expect(screen.getByText(/缺少完整的目标来源证据/)).toBeInTheDocument();
  });

  it("requires feature selection before source validation", () => {
    renderPanel([]);
    expect(screen.getByRole("button", { name: "核验目标来源文件" })).toBeDisabled();
    expect(screen.getByText("先选择至少一个特征，再核验当前 X/y 方案的来源文件。")).toBeInTheDocument();
  });

  it("shows an actionable error and preserves the current target status", async () => {
    vi.mocked(client.validateTargetSourceEvidence).mockRejectedValue(new Error("checksum mismatch"));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={queryClient}>
      <TargetSourcePreflight batteryId="CELL_A" experimentId="EXP_A" target={target} features={["SWA"]} />
    </QueryClientProvider>);
    fireEvent.click(screen.getByRole("button", { name: "核验目标来源文件" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("检查 DataAsset manifest、原始文件与解析产物");
    expect(screen.getByRole("alert")).toHaveTextContent("原有目标状态不会改变。");
  });

  it("does not show a prior verification after the selected features change", async () => {
    vi.mocked(client.validateTargetSourceEvidence).mockResolvedValue({
      data: {
        status: "SOURCE_EVIDENCE_VERIFIED",
        target_id: "reference_soc_percent",
        verified_sources: [{ asset_id: "E001", verified: true, sha256: "a".repeat(64), parser_provenance: "VERIFIED" }],
        source_integrity: "VERIFIED",
        label_source_semantics: "NOT_ASSESSED",
        target_readiness: "NOT_ASSESSED",
        feature_availability: "NOT_ASSESSED",
        materialization_enabled: false,
      },
      meta: {},
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const { rerender } = render(<QueryClientProvider client={queryClient}>
      <TargetSourcePreflight batteryId="CELL_A" experimentId="EXP_A" target={target} features={["SWA"]} />
    </QueryClientProvider>);
    fireEvent.click(screen.getByRole("button", { name: "核验目标来源文件" }));
    expect(await screen.findByTestId("target-source-integrity-status")).toBeInTheDocument();

    rerender(<QueryClientProvider client={queryClient}>
      <TargetSourcePreflight batteryId="CELL_A" experimentId="EXP_A" target={target} features={["tof_us"]} />
    </QueryClientProvider>);
    expect(screen.queryByTestId("target-source-integrity-status")).not.toBeInTheDocument();
  });
});
