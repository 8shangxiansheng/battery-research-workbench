import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError, client } from "../src/api/client";
import { CycleStepMappingPreflight } from "../src/components/workbench/CycleStepMappingPreflight";

function mount() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CycleStepMappingPreflight batteryId="CELL_A" experimentId="EXP_A" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(client, "getCycleStepMappingStatus").mockResolvedValue({
    data: {
      status: "MISSING",
      active_mapping_sha256: null,
      revision_count: 0,
      reason: null,
    },
    meta: { read_only: true },
  });
});

describe("Cycle-Step mapping preflight", () => {
  it("上传 CSV 后显示数量，并明确预检不等于科学验证或保存", async () => {
    const user = userEvent.setup();
    vi.spyOn(client, "preflightCycleStepMapping").mockResolvedValue({
      data: {
        status: "CYCLE_STEP_MAPPING_CONTRACT_VALIDATED",
        contract_version: "cycle-step-mapping/1.0",
        mapping_id: "CSM::REVIEW_001",
        battery_id: "CELL_A",
        experiment_id: "EXP_A",
        mapping_sha256: "a".repeat(64),
        parser_manifest_sha256: "b".repeat(64),
        source_cycle_count: 3,
        source_step_count: 12,
        canonical_cycle_count: 3,
        review_status: "OPERATOR_DECLARED_ACCEPTED_UNAUTHENTICATED",
        mapping_application_status: "LABEL_BUILDER_CONSUMER_AVAILABLE",
        label_generation_authorized: false,
        scientific_cycle_continuity: "NOT_ASSESSED",
      },
      meta: { read_only: true },
    });
    const save = vi.spyOn(client, "saveCycleStepMapping").mockResolvedValue({
      data: {
        status: "CYCLE_STEP_MAPPING_CONTRACT_VALIDATED",
        contract_version: "cycle-step-mapping/1.0",
        mapping_id: "CSM::REVIEW_001",
        battery_id: "CELL_A",
        experiment_id: "EXP_A",
        mapping_sha256: "a".repeat(64),
        parser_manifest_sha256: "b".repeat(64),
        source_cycle_count: 3,
        source_step_count: 12,
        canonical_cycle_count: 3,
        review_status: "OPERATOR_DECLARED_ACCEPTED_UNAUTHENTICATED",
        mapping_application_status: "LABEL_BUILDER_CONSUMER_AVAILABLE",
        label_generation_authorized: false,
        scientific_cycle_continuity: "NOT_ASSESSED",
        save_status: "SAVED",
        previous_mapping_sha256: null,
        revision_count: 1,
        active_mapping_relative_path: "annotations/CELL_A/EXP_A/cycle-step-mapping.csv",
      },
      meta: { read_only: false },
    });
    mount();

    const templateLink = screen.getByRole("link", { name: "下载空白 CSV 模板" });
    expect(templateLink).toHaveAttribute("href", "/cycle-step-mapping.csv");
    expect(templateLink).toHaveAttribute("download", "cycle-step-mapping.csv");

    await user.upload(
      screen.getByLabelText("选择 Cycle-Step 映射 CSV"),
      new File(["contract_version,mapping_id\n"], "mapping.csv", { type: "text/csv" }),
    );
    await user.click(screen.getByRole("button", { name: "预检映射" }));

    expect(client.preflightCycleStepMapping).toHaveBeenCalledWith(
      "CELL_A",
      "EXP_A",
      "contract_version,mapping_id\n",
    );
    const result = await screen.findByTestId("cycle-step-mapping-result");
    expect(result).toHaveTextContent(/来源 Cycle\s*3/);
    expect(result).toHaveTextContent(/来源 Step\s*12/);
    expect(result).toHaveTextContent("审核人身份及 Cycle 连续性的科学解释未验证");
    expect(result).toHaveTextContent("预检本身不会保存");
    expect(screen.getByTestId("cycle-step-mapping-save")).toBeDisabled();
    await user.click(screen.getByTestId("cycle-step-mapping-confirm-reviewed"));
    await user.click(screen.getByTestId("cycle-step-mapping-save"));
    expect(save).toHaveBeenCalledWith("CELL_A", "EXP_A", {
      mapping_csv: "contract_version,mapping_id\n",
      confirm_reviewed: true,
      expected_active_sha256: null,
    });
    expect(await screen.findByTestId("cycle-step-mapping-saved")).toHaveTextContent("不可变版本快照");
  });

  it("展示后端拒绝原因，不显示通过态", async () => {
    const user = userEvent.setup();
    vi.spyOn(client, "preflightCycleStepMapping").mockRejectedValue(
      new ApiError(400, {
        error: {
          code: "VALIDATION_ERROR",
          message: "Cycle/Step mapping preflight failed",
          details: { reason: "mapping must cover every parsed source step exactly once" },
          request_id: "req-test",
        },
      }),
    );
    mount();
    await user.upload(
      screen.getByLabelText("选择 Cycle-Step 映射 CSV"),
      new File(["broken"], "mapping.csv", { type: "text/csv" }),
    );
    await user.click(screen.getByRole("button", { name: "预检映射" }));

    expect(await screen.findByTestId("cycle-step-mapping-error")).toHaveTextContent(
      "mapping must cover every parsed source step exactly once",
    );
    expect(screen.queryByTestId("cycle-step-mapping-result")).not.toBeInTheDocument();
  });

  it("超出 API 上限的文件不能提交", async () => {
    const user = userEvent.setup();
    const preflight = vi.spyOn(client, "preflightCycleStepMapping");
    mount();
    await user.upload(
      screen.getByLabelText("选择 Cycle-Step 映射 CSV"),
      new File([new Uint8Array(4_000_001)], "large.csv", { type: "text/csv" }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent("文件超过 4 MB");
    expect(screen.getByRole("button", { name: "预检映射" })).toBeDisabled();
    expect(preflight).not.toHaveBeenCalled();
  });
});
