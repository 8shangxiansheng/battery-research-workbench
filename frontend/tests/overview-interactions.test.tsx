import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { client, type StatusBlock } from "../src/api/client";
import { OverviewPage } from "../src/pages/redesign/OverviewPage";
import { AssistantProvider, useAssistant } from "../src/components/workbench/AssistantContext";

vi.mock("../src/components/workbench/OverviewSignals", () => ({ ElectricalMiniView: () => <div>Electrical API preview</div>, UltrasoundMiniView: () => <div>Ultrasound API preview</div> }));
const blocked: StatusBlock = { battery_id: "B", experiment_id: "E", synchronization: { validated_sync: false, timebase_status: "PROVISIONAL" }, tof: { status: "BLOCKED", value: null, reason: "sampling required" }, soc: { status: "RETROSPECTIVE_SOC_REFERENCE", value: null, reason: "reference" }, soh: { status: "NOT_READY", value: null, reason: "insufficient states" }, scientific_status: "LIMITED" };
function ContextProbe() { const assistant = useAssistant(); return <output data-testid="assistant-context">{assistant.open ? assistant.question : "closed"}</output>; }
function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={["/experiments/B/E/overview"]}><Routes><Route path="/experiments/:batteryId/:experimentId/*" element={<AssistantProvider><OverviewPage/><ContextProbe/></AssistantProvider>}/></Routes></MemoryRouter></QueryClientProvider>);
  return qc;
}
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(client, "getWorkspaceSummary").mockResolvedValue({ data: { battery_id: "B", experiment_id: "E", gate_set_id: "g" } } as Awaited<ReturnType<typeof client.getWorkspaceSummary>>);
  vi.spyOn(client, "getStatus").mockResolvedValue({ data: blocked });
  vi.spyOn(client, "getDataQuality").mockResolvedValue({ data: { battery_id: "B", experiment_id: "E", electrical: null, ultrasound: null } });
  vi.spyOn(client, "getResults").mockResolvedValue({ data: [] });
});
describe("概览交互闭环", () => {
  it("前置条件在原地打开，重新检查后只接受 API 验证结果", async () => {
    mount(); const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "完善前置参数" }));
    const drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText(/尚未验证；/)).toBeInTheDocument();
    vi.mocked(client.getStatus).mockResolvedValue({ data: { ...blocked, synchronization: { validated_sync: true, timebase_status: "VERIFIED" }, tof: { value: 2, status: "AVAILABLE", reason: "" } } });
    await user.click(within(drawer).getByRole("button", { name: "重新检查后端状态" }));
    await waitFor(() => expect(within(drawer).getByText("验证通过")).toBeInTheDocument());
    expect(screen.getByTestId("overview-primary")).toHaveAttribute("href", "/experiments/B/E/analysis");
  });
  it("采样率保存后刷新状态但不伪造验证通过（BRW-018R2 共享提交服务）", async () => {
    vi.spyOn(client, "submitSamplingParameter").mockResolvedValue({
      data: {
        submission_id: "SUB::t", parameter_set_id: "p", save_status: "SAVED",
        save_error: null, fs_value: 20_000_000, fs_unit: "Hz", source: "instrument configuration",
        run_id: null, pending_action_resolved: false, resume_status: "NOT_ATTEMPTED",
        resume_error: null, run_state: null,
      },
    } as Awaited<ReturnType<typeof client.submitSamplingParameter>>);
    mount(); const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add sampling rate" }));
    await user.type(screen.getByTestId("fs-dialog-value"), "20");
    await user.type(screen.getByLabelText("Instrument record or source"), "instrument configuration");
    // verified checkbox intentionally NOT checked → honest UNVERIFIED save
    await user.click(screen.getByTestId("fs-dialog-save"));
    expect(await screen.findByTestId("submission-saved")).toBeInTheDocument();
    expect(client.submitSamplingParameter).toHaveBeenCalledWith("B", "E", expect.objectContaining({
      verified: false,
      values: { "ultrasound.sampling_rate_hz": { value: 20, unit: "MHz" } },
    }));
    await waitFor(() => expect(client.getStatus).toHaveBeenCalledTimes(2));
    // UNVERIFIED fs must not flip the overview primary into a verified state
    expect(screen.getByTestId("overview-primary")).toHaveTextContent("完善前置参数");
  });
  it("报错上下文进入全局助手，不发送 AI 请求", async () => {
    mount(); const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "携带阻断上下文询问助手" }));
    expect(screen.getByTestId("assistant-context")).toHaveTextContent("sampling required");
  });
  it("调优入口明确能力限制，不假装启动训练", async () => {
    mount(); const user = userEvent.setup();
    await user.click(await screen.findByText("排查建议与下一步"));
    await user.click(screen.getByRole("button", { name: "重新配置超参数" }));
    expect(screen.getByText("当前 API 不支持调优")).toBeInTheDocument();
  });
});
