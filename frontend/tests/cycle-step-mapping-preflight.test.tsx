import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
    const draftLink = screen.getByTestId("cycle-step-mapping-download-draft");
    expect(draftLink).toHaveAttribute(
      "href",
      "/api/v1/experiments/CELL_A/EXP_A/cycle-step-mapping/draft",
    );
    expect(draftLink).toHaveAttribute("download", "cycle-step-mapping-draft-CELL_A-EXP_A.csv");
    expect(screen.getByText(/canonical Cycle\/Step、审核人和理由保持空白/)).toBeInTheDocument();

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

  it("读取当前映射失败时可显式重试", async () => {
    const user = userEvent.setup();
    const status = vi.spyOn(client, "getCycleStepMappingStatus");
    status
      .mockRejectedValueOnce(new Error("service unavailable"))
      .mockResolvedValueOnce({
        data: {
          status: "MISSING",
          active_mapping_sha256: null,
          revision_count: 0,
          reason: null,
        },
        meta: { read_only: true },
      });
    mount();

    expect(await screen.findByRole("alert")).toHaveTextContent("无法读取当前映射版本");
    await user.click(screen.getByRole("button", { name: "重试读取映射状态" }));

    expect(await screen.findByTestId("cycle-step-mapping-current")).toHaveTextContent(
      "当前没有已保存映射",
    );
  });

  it("过期映射显示重新审核的恢复路径", async () => {
    vi.spyOn(client, "getCycleStepMappingStatus").mockResolvedValue({
      data: {
        status: "INVALID",
        active_mapping_sha256: "d".repeat(64),
        revision_count: 2,
        reason: "parser manifest changed after review",
      },
      meta: { read_only: true },
    });
    mount();

    expect(await screen.findByTestId("cycle-step-mapping-current")).toHaveTextContent(
      "当前映射无效或过期：parser manifest changed after review",
    );
    expect(screen.getByRole("note")).toHaveTextContent(
      "修订映射，重新预检并确认后保存新版本",
    );
  });

  it("历史快照完整性失败时给出备份恢复说明且不静默覆盖", async () => {
    const user = userEvent.setup();
    vi.spyOn(client, "getCycleStepMappingStatus")
      .mockRejectedValueOnce(new ApiError(409, {
        error: {
          code: "INTEGRITY_ERROR",
          message: "content-addressed mapping revision is inconsistent",
          details: {},
          request_id: "req-integrity",
        },
      }))
      .mockResolvedValueOnce({
        data: {
          status: "VALIDATED",
          active_mapping_sha256: "e".repeat(64),
          revision_count: 1,
          reason: null,
        },
        meta: { read_only: true },
      });
    mount();

    const integrityError = await screen.findByRole("alert");
    expect(integrityError).toHaveTextContent("完整性校验未通过");
    expect(integrityError).toHaveTextContent("从可信副本恢复");
    expect(integrityError).toHaveTextContent("不要删除或改写损坏快照");
    await user.click(screen.getByRole("button", { name: "重试读取映射状态" }));

    expect(await screen.findByTestId("cycle-step-mapping-current")).toHaveTextContent(
      "当前映射结构与来源 checksum 已验证",
    );
  });

  it("可查看并下载内容校验过的 Cycle-Step 映射历史版本", async () => {
    const user = userEvent.setup();
    const activeHash = "a".repeat(64);
    const previousHash = "b".repeat(64);
    vi.spyOn(client, "getCycleStepMappingStatus").mockResolvedValue({
      data: {
        status: "VALIDATED",
        active_mapping_sha256: activeHash,
        revision_count: 2,
        reason: null,
      },
      meta: { read_only: true },
    });
    const listRevisions = vi.spyOn(client, "getCycleStepMappingRevisions").mockResolvedValue({
      data: {
        revisions: [
          { sha256: activeHash, size_bytes: 500, is_active: true },
          { sha256: previousHash, size_bytes: 450, is_active: false },
        ],
      },
      meta: { read_only: true },
    });
    mount();

    await user.click(await screen.findByTestId("cycle-step-mapping-toggle-history"));
    expect(listRevisions).toHaveBeenCalledWith("CELL_A", "EXP_A");
    const history = await screen.findByTestId("cycle-step-mapping-history");
    expect(history).toHaveTextContent("当前活动版本");
    expect(history).toHaveTextContent("不代表该历史版本仍匹配当前 parser/raw");
    const download = screen.getAllByRole("link", { name: "下载 CSV" })[0];
    expect(download).toHaveAttribute(
      "href",
      `/api/v1/experiments/CELL_A/EXP_A/cycle-step-mapping/revisions/${activeHash}`,
    );
    expect(download).toHaveAttribute("download", `cycle-step-mapping-${activeHash}.csv`);
  });

  it("保存冲突后清除旧审核确认并刷新版本状态", async () => {
    const user = userEvent.setup();
    const status = vi.spyOn(client, "getCycleStepMappingStatus");
    status
      .mockResolvedValueOnce({
        data: {
          status: "MISSING",
          active_mapping_sha256: null,
          revision_count: 0,
          reason: null,
        },
        meta: { read_only: true },
      })
      .mockResolvedValueOnce({
        data: {
          status: "VALIDATED",
          active_mapping_sha256: "c".repeat(64),
          revision_count: 1,
          reason: null,
        },
        meta: { read_only: true },
      });
    vi.spyOn(client, "preflightCycleStepMapping").mockResolvedValue({
      data: {
        status: "CYCLE_STEP_MAPPING_CONTRACT_VALIDATED",
        contract_version: "cycle-step-mapping/1.0",
        mapping_id: "CSM::REVIEW_001",
        battery_id: "CELL_A",
        experiment_id: "EXP_A",
        mapping_sha256: "a".repeat(64),
        parser_manifest_sha256: "b".repeat(64),
        source_cycle_count: 1,
        source_step_count: 1,
        canonical_cycle_count: 1,
        review_status: "OPERATOR_DECLARED_ACCEPTED_UNAUTHENTICATED",
        mapping_application_status: "LABEL_BUILDER_CONSUMER_AVAILABLE",
        label_generation_authorized: false,
        scientific_cycle_continuity: "NOT_ASSESSED",
      },
      meta: { read_only: true },
    });
    const save = vi.spyOn(client, "saveCycleStepMapping");
    save
      .mockRejectedValueOnce(new ApiError(409, {
        error: {
          code: "CONFLICT",
          message: "active mapping changed",
          details: {},
          request_id: "req-conflict",
        },
      }))
      .mockResolvedValueOnce({
        data: {
          status: "CYCLE_STEP_MAPPING_CONTRACT_VALIDATED",
          contract_version: "cycle-step-mapping/1.0",
          mapping_id: "CSM::REVIEW_001",
          battery_id: "CELL_A",
          experiment_id: "EXP_A",
          mapping_sha256: "a".repeat(64),
          parser_manifest_sha256: "b".repeat(64),
          source_cycle_count: 1,
          source_step_count: 1,
          canonical_cycle_count: 1,
          review_status: "OPERATOR_DECLARED_ACCEPTED_UNAUTHENTICATED",
          mapping_application_status: "LABEL_BUILDER_CONSUMER_AVAILABLE",
          label_generation_authorized: false,
          scientific_cycle_continuity: "NOT_ASSESSED",
          save_status: "SAVED",
          previous_mapping_sha256: "c".repeat(64),
          revision_count: 2,
          active_mapping_relative_path: "annotations/CELL_A/EXP_A/cycle-step-mapping.csv",
        },
        meta: { read_only: false },
      });
    mount();
    const file = new File(["mapping"], "mapping.csv", { type: "text/csv" });
    const fileInput = screen.getByLabelText("选择 Cycle-Step 映射 CSV");
    await user.upload(fileInput, file);
    await user.click(screen.getByRole("button", { name: "预检映射" }));
    await screen.findByTestId("cycle-step-mapping-result");
    await user.click(screen.getByTestId("cycle-step-mapping-confirm-reviewed"));
    await user.click(screen.getByTestId("cycle-step-mapping-save"));

    expect(await screen.findByTestId("cycle-step-mapping-save-error")).toHaveTextContent(
      "检测到映射版本冲突",
    );
    expect(screen.queryByTestId("cycle-step-mapping-result")).not.toBeInTheDocument();
    expect(screen.queryByTestId("cycle-step-mapping-confirm-reviewed")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("cycle-step-mapping-current")).toHaveTextContent(
      "当前版本 cccccccccccc",
    ));

    await user.upload(fileInput, file);
    await user.click(screen.getByRole("button", { name: "预检映射" }));
    await screen.findByTestId("cycle-step-mapping-result");
    await user.click(screen.getByTestId("cycle-step-mapping-confirm-reviewed"));
    await user.click(screen.getByTestId("cycle-step-mapping-save"));

    expect(await screen.findByTestId("cycle-step-mapping-saved")).toBeInTheDocument();
    expect(save).toHaveBeenLastCalledWith("CELL_A", "EXP_A", {
      mapping_csv: "mapping",
      confirm_reviewed: true,
      expected_active_sha256: "c".repeat(64),
    });
  });
});
