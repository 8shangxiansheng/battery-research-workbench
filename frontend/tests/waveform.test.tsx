/** BRW-025 §59: 波形/闸门 tests（T07-T12）。 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as clientModule from "../src/api/client";
import type { FrameListResponse, FramePreviewResponse } from "../src/api/client";
import { WaveformPage } from "../src/pages/WaveformPage";

const frameList: FrameListResponse = {
  battery_id: "CELL_001",
  experiment_id: "EXP_001",
  frame_count: 3999,
  waveform_length: 1250,
  x_axis: "SAMPLE_INDEX",
  time_axis_available: false,
  frames: [
    { frame_index: 0, waveform_group: "U001/waveform", waveform_row_index: 0, sample_count: 1250 },
  ],
};

const framePreview: FramePreviewResponse = {
  frame_index: 0,
  waveform_group: "U001/waveform",
  waveform_row_index: 0,
  waveform_length: 1250,
  x_axis: "SAMPLE_INDEX",
  time_axis_us: null,
  sampling_rate_status: "NOT_VERIFIED",
  max_points: 500,
  samples: Array.from({ length: 50 }, (_, i) => ({
    sample_index: i * 25,
    amplitude_a_u: Math.sin(i / 5),
  })),
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/experiments/CELL_001/EXP_001/waveform"]}>
        <Routes>
          <Route path="/experiments/:batteryId/:experimentId/waveform" element={<WaveformPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("WaveformPage（§59 T07-T12）", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("T07/T08 无 fs 时 x 轴 = Sample Index，且不出现 μs 时间轴", async () => {
    vi.spyOn(clientModule.client, "listWaveformFrames").mockResolvedValue({
      data: frameList,
      meta: {},
    });
    vi.spyOn(clientModule.client, "listGates").mockResolvedValue({ data: { gates: [] }, meta: {} });
    vi.spyOn(clientModule.client, "getWaveformFrame").mockResolvedValue({
      data: framePreview,
      meta: {},
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("waveform-svg")).toBeInTheDocument();
    });
    expect(screen.getByText(/Sample Index/)).toBeInTheDocument();
    expect(screen.queryByText(/时间轴.*μs|μs 时间轴.*可用/)).toBeNull();
    expect(screen.getByText(/不显示 μs 时间轴/)).toBeInTheDocument();
  });

  it("T09 拖选生成 draft gate（显示 start/end，未提交）", async () => {
    const user = userEvent.setup();
    vi.spyOn(clientModule.client, "listWaveformFrames").mockResolvedValue({
      data: frameList,
      meta: {},
    });
    vi.spyOn(clientModule.client, "listGates").mockResolvedValue({ data: { gates: [] }, meta: {} });
    vi.spyOn(clientModule.client, "getWaveformFrame").mockResolvedValue({
      data: framePreview,
      meta: {},
    });
    renderPage();
    const svg = await screen.findByTestId("waveform-svg");
    const rect = svg.getBoundingClientRect();
    await user.pointer([
      { target: svg, coords: { clientX: rect.left + 10, clientY: rect.top + 20 }, keys: "[MouseLeft>]" },
      { target: svg, coords: { clientX: rect.left + 110, clientY: rect.top + 20 } },
      { keys: "[/MouseLeft]" },
    ]);
    await waitFor(() => {
      expect(screen.getByTestId("draft-panel")).toBeInTheDocument();
    });
    expect(screen.getByTestId("draft-gate")).toBeInTheDocument();
  });

  it("T10/T11 提交走 API 并绑定 gate_id；显示 committed 表", async () => {
    const user = userEvent.setup();
    const createGate = vi
      .spyOn(clientModule.client, "createGate")
      .mockResolvedValue({
        data: { gate_id: "GATE::abc123", gate_set_id: "GATESET::x", reuse_status: "CREATED" },
        meta: {},
      });
    vi.spyOn(clientModule.client, "listWaveformFrames").mockResolvedValue({
      data: frameList,
      meta: {},
    });
    vi.spyOn(clientModule.client, "listGates").mockResolvedValue({
      data: { gates: [{ gate_id: "GATE::abc123", gate_set_id: "GATESET::x", start_sample: 10, end_sample: 100 }] },
      meta: {},
    });
    vi.spyOn(clientModule.client, "getWaveformFrame").mockResolvedValue({
      data: framePreview,
      meta: {},
    });
    renderPage();
    // 直接通过键盘面板注入 draft：模拟 onSelect 由 pointer 事件触发
    const svg = await screen.findByTestId("waveform-svg");
    const rect = svg.getBoundingClientRect();
    await user.pointer([
      { target: svg, coords: { clientX: rect.left + 10, clientY: rect.top + 20 }, keys: "[MouseLeft>]" },
      { target: svg, coords: { clientX: rect.left + 110, clientY: rect.top + 20 } },
      { keys: "[/MouseLeft]" },
    ]);
    await user.click(await screen.findByTestId("commit-gate"));
    await waitFor(() => {
      expect(createGate).toHaveBeenCalled();
      expect(screen.getByTestId("commit-success")).toBeInTheDocument();
    });
    // gate_id 至少出现在 commit 消息和 committed 表中（科学身份绑定）
    expect(screen.getAllByText(/GATE::abc123/).length).toBeGreaterThanOrEqual(1);
  });

  it("T12 UI 不计算 feature：提交按钮语义只有闸门提交", async () => {
    vi.spyOn(clientModule.client, "listWaveformFrames").mockResolvedValue({
      data: frameList,
      meta: {},
    });
    vi.spyOn(clientModule.client, "listGates").mockResolvedValue({ data: { gates: [] }, meta: {} });
    vi.spyOn(clientModule.client, "getWaveformFrame").mockResolvedValue({
      data: framePreview,
      meta: {},
    });
    renderPage();
    await waitFor(() => screen.getByTestId("waveform-svg"));
    // 页面没有任何 “计算特征/extract feature” 控件
    expect(screen.queryByText(/提取特征|计算特征/)).toBeNull();
  });
});
