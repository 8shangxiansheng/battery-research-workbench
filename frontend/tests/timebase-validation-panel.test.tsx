import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { client } from "../src/api/client";
import { TimebaseValidationPanel } from "../src/components/workbench/TimebaseValidationPanel";

function mount() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={queryClient}><TimebaseValidationPanel batteryId="CELL_001" experimentId="EXP_001" /></QueryClientProvider>);
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(client, "listExperimentAssets").mockResolvedValue({ data: { assets: [
    { asset_id: "U001", battery_id: "CELL_001", experiment_id: "EXP_001", modality: "ultrasound", relative_path: "ultrasound/u001.txt", sha256: "a".repeat(64) },
  ] } } as Awaited<ReturnType<typeof client.listExperimentAssets>>);
  vi.spyOn(client, "listTimebaseValidations").mockResolvedValue({ data: { validations: [] } });
});

describe("时间基准证据表单", () => {
  it("预检服务器 raw 文件并自动填入 anchor SHA-256，修改路径后使旧结果失效", async () => {
    const clockRef = "batteries/CELL_001/EXP_001/timebase_evidence/clock-log.csv";
    const checksum = "c".repeat(64);
    vi.spyOn(client, "preflightTimebaseEvidence").mockResolvedValue({
      data: {
        status: "SOURCE_FILES_VERIFIED",
        source_integrity: "VERIFIED",
        verified_evidence: { [clockRef]: { sha256: checksum, size_bytes: 80 } },
      },
      meta: { read_only: true, scientific_validity: "NOT_ASSESSED" },
    });
    mount();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("timebase-open"));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("U001 来源引用"), clockRef);
    await user.click(within(dialog).getByTestId("timebase-evidence-preflight"));

    expect(await within(dialog).findByTestId("timebase-evidence-preflight-result")).toHaveTextContent("已核验 1 个证据文件");
    expect(within(dialog).getByLabelText("U001 来源 SHA-256")).toHaveValue(checksum);
    expect(within(dialog).getByLabelText("锚点证据文件路径（相对 data/raw，每行一项）")).toHaveValue(clockRef);
    expect(client.preflightTimebaseEvidence).toHaveBeenCalledWith("CELL_001", "EXP_001", [clockRef]);

    await user.clear(within(dialog).getByLabelText("U001 来源引用"));
    await user.type(within(dialog).getByLabelText("U001 来源引用"), `${clockRef}.changed`);
    expect(within(dialog).queryByTestId("timebase-evidence-preflight-result")).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("U001 来源 SHA-256")).toHaveValue("");
  });

  it("可以从列表恢复已有 provisional 审核记录和事件历史", async () => {
    vi.mocked(client.listTimebaseValidations).mockResolvedValue({ data: { validations: [
      { validation_id: "TBV::existing", status: "PROVISIONAL", submitted_at: "2026-10-06T00:00:00Z", asset_ids: ["U001"], validated_sync: false },
    ] } });
    vi.spyOn(client, "getTimebaseValidation").mockResolvedValue({ data: {
      validation_id: "TBV::existing", status: "PROVISIONAL", validated_sync: false,
      events: [{ event_type: "SUBMITTED", status: "PROVISIONAL" }],
    } });
    mount();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("timebase-open"));
    const dialog = await screen.findByRole("dialog");
    await user.click(await within(dialog).findByRole("button", { name: "打开记录" }));
    expect(await within(dialog).findByText("TBV::existing")).toBeInTheDocument();
    expect(within(dialog).getByText("审计事件记录（1）")).toBeInTheDocument();
  });

  it("历史证据变更时显示 stale 并阻止接受", async () => {
    vi.mocked(client.listTimebaseValidations).mockResolvedValue({ data: { validations: [
      {
        validation_id: "TBV::stale", status: "PROVISIONAL", effective_status: "STALE_EVIDENCE",
        evidence_integrity_status: "STALE_EVIDENCE", submitted_at: "2026-10-06T00:00:00Z",
        asset_ids: ["U001"], validated_sync: false,
      },
    ] } });
    vi.spyOn(client, "getTimebaseValidation").mockResolvedValue({ data: {
      validation_id: "TBV::stale", status: "PROVISIONAL", effective_status: "STALE_EVIDENCE",
      evidence_integrity_status: "STALE_EVIDENCE", validated_sync: false,
      events: [{ event_type: "SUBMITTED", status: "PROVISIONAL" }],
    } });
    mount();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("timebase-open"));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findAllByText(/STALE_EVIDENCE/)).toHaveLength(2);
    await user.click(within(dialog).getByRole("button", { name: "打开记录" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("证据文件与记录的 SHA-256 不一致");
    expect(within(dialog).getByRole("button", { name: "记录审核接受" })).toBeDisabled();
  });

  it("审核证据审计记录无效时阻止接受与应用，并保留撤销路径", async () => {
    vi.mocked(client.listTimebaseValidations).mockResolvedValue({ data: { validations: [
      {
        validation_id: "TBV::invalid", status: "ACCEPTED_PENDING_RECOMPUTE",
        effective_status: "INVALID_RECORD", evidence_integrity_status: "INVALID_RECORD",
        submitted_at: "2026-10-06T00:00:00Z", asset_ids: ["U001"], validated_sync: false,
      },
    ] } });
    vi.spyOn(client, "getTimebaseValidation").mockResolvedValue({ data: {
      validation_id: "TBV::invalid", status: "ACCEPTED_PENDING_RECOMPUTE",
      effective_status: "INVALID_RECORD", evidence_integrity_status: "INVALID_RECORD",
      validated_sync: false, events: [{ event_type: "SUBMITTED" }, { event_type: "REVIEWED" }],
    } });
    mount();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("timebase-open"));
    const dialog = await screen.findByRole("dialog");
    await user.click(await within(dialog).findByRole("button", { name: "打开记录" }));

    expect(await within(dialog).findByText(/审核证据审计记录格式无效/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "应用已接受锚点并重算同步" })).toBeDisabled();
    await user.type(within(dialog).getByLabelText("撤销操作者身份"), "reviewer@example.org");
    await user.type(within(dialog).getByLabelText("撤销理由"), "撤销无法验证的审核记录");
    expect(within(dialog).getByRole("button", { name: "撤销审核接受" })).toBeEnabled();
  });

  it.each(["INVALID_RECORD", "NOT_VERIFIED"] as const)(
    "proposal 证据为 %s 时，即使审核字段完整也不能接受",
    async integrityStatus => {
      vi.mocked(client.listTimebaseValidations).mockResolvedValue({ data: { validations: [
        {
          validation_id: "TBV::unusable-proposal", status: "PROVISIONAL",
          effective_status: integrityStatus, evidence_integrity_status: integrityStatus,
          submitted_at: "2026-10-06T00:00:00Z", asset_ids: ["U001"], validated_sync: false,
        },
      ] } });
      vi.spyOn(client, "getTimebaseValidation").mockResolvedValue({ data: {
        validation_id: "TBV::unusable-proposal", status: "PROVISIONAL",
        effective_status: integrityStatus, evidence_integrity_status: integrityStatus,
        validated_sync: false, events: [{ event_type: "SUBMITTED", status: "PROVISIONAL" }],
      } });
      mount();
      const user = userEvent.setup();
      await user.click(screen.getByTestId("timebase-open"));
      const dialog = await screen.findByRole("dialog");
      await user.click(await within(dialog).findByRole("button", { name: "打开记录" }));
      await user.type(within(dialog).getByLabelText("操作者身份"), "reviewer@example.org");
      await user.type(within(dialog).getByLabelText("审核理由"), "检查校准证据");
      await user.type(within(dialog).getByLabelText("U001 误差（秒）"), "0.2");
      await user.click(within(dialog).getByLabelText("已检查该资产无未解决时间歧义"));
      await user.type(within(dialog).getByLabelText("审核证据文件路径（相对 data/raw，每行一项）"), "pulse-review.csv");

      expect(within(dialog).getByRole("button", { name: "记录审核接受" })).toBeDisabled();
      expect(within(dialog).getByTestId("timebase-current-evidence-integrity")).toHaveTextContent(integrityStatus);
    },
  );

  it("提交锚点后通过逐资产审核记录待重算状态，不伪造同步验证", async () => {
    const clockRef = "batteries/CELL_001/EXP_001/timebase_evidence/clock-log.csv";
    vi.spyOn(client, "submitTimebaseValidation").mockResolvedValue({ data: {
      validation_id: "TBV::abc", status: "PROVISIONAL", validated_sync: false,
    } });
    vi.spyOn(client, "preflightTimebaseEvidence").mockResolvedValue({
      data: {
        status: "SOURCE_FILES_VERIFIED",
        source_integrity: "VERIFIED",
        verified_evidence: { [clockRef]: { sha256: "b".repeat(64), size_bytes: 80 } },
      },
      meta: { read_only: true, scientific_validity: "NOT_ASSESSED" },
    });
    vi.spyOn(client, "reviewTimebaseValidation").mockResolvedValue({ data: {
      validation_id: "TBV::abc", status: "ACCEPTED_PENDING_RECOMPUTE", validated_sync: false,
    } });
    vi.spyOn(client, "startRun").mockResolvedValue({ data: {
      run_id: "RUN::timebase", state: "SUCCEEDED",
    } });
    vi.spyOn(client, "getTimebaseValidation").mockResolvedValue({ data: {
      validation_id: "TBV::abc", status: "RECOMPUTED_PROVISIONAL", validated_sync: false,
      events: [{ event_type: "SUBMITTED" }, { event_type: "REVIEWED" }, { event_type: "ANCHOR_RECOMPUTED" }],
    } });
    mount();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("timebase-open"));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("IANA 时区"), "Asia/Shanghai");
    await user.clear(within(dialog).getByLabelText("允许误差（秒）"));
    await user.type(within(dialog).getByLabelText("允许误差（秒）"), "0.5");
    await user.type(within(dialog).getByLabelText("U001 绝对起始时间"), "2024-01-06T21:03:01+08:00");
    await user.type(within(dialog).getByLabelText("U001 来源引用"), clockRef);
    await user.type(within(dialog).getByLabelText("锚点证据文件路径（相对 data/raw，每行一项）"), clockRef);
    await user.click(within(dialog).getByTestId("timebase-evidence-preflight"));
    expect(await within(dialog).findByTestId("timebase-evidence-preflight-result")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("U001 来源 SHA-256")).toHaveValue("b".repeat(64));
    await user.click(within(dialog).getByRole("button", { name: "提交为 PROVISIONAL" }));
    await waitFor(() => expect(client.submitTimebaseValidation).toHaveBeenCalledWith("CELL_001", "EXP_001", expect.objectContaining({
      timezone: "Asia/Shanghai",
      contract_version: "timebase-validation/1.1",
      anchors: [expect.objectContaining({ asset_id: "U001", absolute_start_time: "2024-01-06T21:03:01+08:00" })],
    })));
    await user.type(within(dialog).getByLabelText("操作者身份"), "operator@example.org");
    await user.type(within(dialog).getByLabelText("审核理由"), "与脉冲校准记录核对");
    await user.type(within(dialog).getByLabelText("U001 误差（秒）"), "0.2");
    await user.click(within(dialog).getByLabelText("已检查该资产无未解决时间歧义"));
    await user.type(within(dialog).getByLabelText("审核证据文件路径（相对 data/raw，每行一项）"), "batteries/CELL_001/EXP_001/timebase_evidence/pulse-audit.csv");
    await user.click(within(dialog).getByRole("button", { name: "记录审核接受" }));
    await waitFor(() => expect(client.reviewTimebaseValidation).toHaveBeenCalledWith(
      "CELL_001", "EXP_001", "TBV::abc", expect.objectContaining({
        decision: "ACCEPT", error_by_asset_s: { U001: 0.2 }, ambiguity_free_assets: ["U001"],
      }),
    ));
    expect(await within(dialog).findByText("审核声明已记录；需运行同步重算，validated_sync 保持 false。")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "应用已接受锚点并重算同步" }));
    await waitFor(() => expect(client.startRun).toHaveBeenCalledWith(expect.objectContaining({
      profile: "INGEST_TO_MEASUREMENT_EVENTS",
      parameters: { timebase_validation_id: "TBV::abc" },
    })));
    expect(await within(dialog).findByText("已接受锚点已写入 provisional 时间锚点状态；冲突/覆盖诊断仍须检查，声电同步尚未 validated。")).toBeInTheDocument();
  });
});
