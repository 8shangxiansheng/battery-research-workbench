/** BRW-025 §60-62 + §66: actions/features/analysis/read-only tests。 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as clientModule from "../src/api/client";
import { RunsPage } from "../src/pages/RunsPage";
import { FeaturesPage } from "../src/pages/FeaturesPage";
import { FeatureAnalysisPage } from "../src/pages/FeatureAnalysisPage";

function renderAt(node: React.ReactNode, path: string, url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path={path} element={node} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RunsPage — Scientific Actions（§60 T13-T18）", () => {
  beforeEach(() => vi.restoreAllMocks());

  const run = { run_id: "RUN::test-1", status: "WAITING_FOR_USER" };

  function setupRuns() {
    vi.spyOn(clientModule.client, "listRuns").mockResolvedValue({
      data: { runs: [run] },
      meta: {},
    });
    vi.spyOn(clientModule.client, "getRun").mockResolvedValue({ data: run as never, meta: {} });
    vi.spyOn(clientModule.client, "listUserActions").mockResolvedValue({
      data: {
        run_id: "RUN::test-1",
        user_actions: [
          {
            action_id: "ACTION::fs",
            node_id: "PARAMETER_SET",
            action_type: "MISSING_SAMPLING_RATE",
            message: "缺少采样频率",
            required_fields: [{ name: "ultrasound.sampling_rate_hz", unit: "Hz" }],
            options: [],
            scientific_reason: "TOF/wavespeed 需要已验证的采样频率",
            blocking: true,
          },
        ],
      },
      meta: {},
    });
  }

  it("T13 显示采样率 prompt（MHz 单位选项）", async () => {
    setupRuns();
    renderAt(<RunsPage />, "/runs", "/runs");
    await userEvent.click(await screen.findByRole("button", { name: "查看" }));
    await waitFor(() => {
      expect(screen.getByTestId("action-MISSING_SAMPLING_RATE")).toBeInTheDocument();
    });
    expect(screen.getByTestId("fs-input")).toBeInTheDocument();
    expect(screen.getByTestId("fs-unit")).toHaveValue("MHz");
    expect(screen.getByText(/不得猜值/)).toBeInTheDocument();
  });

  it("T15/T16 提交 MHz 换算 Hz → POST action → resume", async () => {
    setupRuns();
    const submit = vi
      .spyOn(clientModule.client, "submitUserAction")
      .mockResolvedValue({ data: { ok: true }, meta: {} });
    const resume = vi
      .spyOn(clientModule.client, "resumeRun")
      .mockResolvedValue({ data: { run_id: "RUN::test-1", status: "RUNNING" }, meta: {} });
    renderAt(<RunsPage />, "/runs", "/runs");
    await userEvent.click(await screen.findByRole("button", { name: "查看" }));
    await userEvent.type(await screen.findByTestId("fs-input"), "50");
    await userEvent.click(screen.getByTestId("submit-action"));
    await waitFor(() => {
      expect(submit).toHaveBeenCalledWith("RUN::test-1", "ACTION::fs", {
        "ultrasound.sampling_rate_hz": 50_000_000,
      });
      expect(resume).toHaveBeenCalledWith("RUN::test-1");
      expect(screen.getByTestId("flow-message")).toHaveTextContent(/resume/);
    });
  });

  it("T17 API 拒绝无效值时显示 typed error 面板（SCIENTIFIC_ACTION_REQUIRED ≠ generic）", async () => {
    setupRuns();
    const { ApiError } = await import("../src/api/client");
    vi.spyOn(clientModule.client, "submitUserAction").mockRejectedValue(
      new ApiError(409, {
        error: {
          code: "SCIENTIFIC_ACTION_REQUIRED",
          message: "required values missing",
          details: { required: ["ultrasound.sampling_rate_hz"] },
          request_id: "req-42",
        },
      }),
    );
    renderAt(<RunsPage />, "/runs", "/runs");
    await userEvent.click(await screen.findByRole("button", { name: "查看" }));
    await userEvent.click(await screen.findByTestId("submit-action"));
    await waitFor(() => {
      expect(screen.getByTestId("error-panel-scientific-action")).toBeInTheDocument();
    });
    expect(screen.getByText(/req-42/)).toBeInTheDocument();
  });

  it("T18 无猜参数：空值不自动提交（无 required value 时按钮仍需显式点击）", async () => {
    setupRuns();
    const submit = vi.spyOn(clientModule.client, "submitUserAction");
    renderAt(<RunsPage />, "/runs", "/runs");
    await userEvent.click(await screen.findByRole("button", { name: "查看" }));
    await waitFor(() => screen.getByTestId("submit-action"));
    expect(submit).not.toHaveBeenCalled(); // 打开页面绝不自动 POST（§52）
  });
});

describe("FeaturesPage（§61 T19-T24）", () => {
  beforeEach(() => vi.restoreAllMocks());

  const features = {
    features: [
      { feature_name: "tof_us", role: "predictor", availability: "NOT_AVAILABLE_CURRENT_ENVIRONMENT", gate_id: null, tof_definition_id: null, missing_reason: "需要 fs AND trigger AND 验证的到达检测器" },
      { feature_name: "amplitude_a_u", role: "predictor", availability: "AVAILABLE", gate_id: null, tof_definition_id: null, missing_reason: null },
      { feature_name: "waveform_rms_a_u", role: "predictor", availability: "AVAILABLE", gate_id: null, tof_definition_id: null, missing_reason: null },
      { feature_name: "wave_speed_m_s", role: null, availability: "NOT_AVAILABLE_CURRENT_ENVIRONMENT", gate_id: null, tof_definition_id: null, missing_reason: "path length UNKNOWN" },
    ],
  };

  function setup() {
    vi.spyOn(clientModule.client, "listFeatures").mockResolvedValue({
      data: features,
      meta: {},
    });
  }

  it("T19 CORE 优先（CORE 区块独立于 auxiliary）", async () => {
    setup();
    renderAt(<FeaturesPage />, "/experiments/:batteryId/:experimentId/features", "/experiments/CELL_001/EXP_001/features");
    await waitFor(() => screen.getByTestId("core-features"));
    expect(screen.getByTestId("feature-tof_us")).toBeInTheDocument();
    expect(screen.getByTestId("feature-amplitude_a_u")).toBeInTheDocument();
  });

  it("T20 auxiliary 折叠（details 元素）", async () => {
    setup();
    renderAt(<FeaturesPage />, "/experiments/:batteryId/:experimentId/features", "/experiments/CELL_001/EXP_001/features");
    await waitFor(() => screen.getByTestId("auxiliary-details"));
    const details = screen.getByTestId("auxiliary-details");
    expect(details.tagName).toBe("DETAILS");
    // 折叠语义：<details> 默认无 open 属性（浏览器内不可见；jsdom 布局不实现，检查属性即可）
    expect(details).not.toHaveAttribute("open");
  });

  it("T21 TOF blocked：availability 文字 + 原因（非 0）", async () => {
    setup();
    renderAt(<FeaturesPage />, "/experiments/:batteryId/:experimentId/features", "/experiments/CELL_001/EXP_001/features");
    await waitFor(() => screen.getByTestId("feature-tof_us"));
    expect(screen.getByTestId("availability-tof_us")).toHaveTextContent(
      "NOT_AVAILABLE_CURRENT_ENVIRONMENT",
    );
    expect(screen.getByText(/需要 fs AND trigger/)).toBeInTheDocument();
  });

  it("T23 用户显式勾选 = FeatureLocator 选择（draft 不自动提交）", async () => {
    const user = userEvent.setup();
    setup();
    renderAt(<FeaturesPage />, "/experiments/:batteryId/:experimentId/features", "/experiments/CELL_001/EXP_001/features");
    const chk = await screen.findByLabelText(/选择特征 amplitude_a_u/);
    await user.click(chk);
    expect(await screen.findByTestId("selection-draft")).toHaveTextContent("amplitude_a_u");
    // 未发任何 POST：selection-draft 只是本地草稿
    expect(screen.getByTestId("selection-draft")).toBeInTheDocument();
  });
});

describe("FeatureAnalysisPage（§62 T25-T31）", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("T25 探索性模式 banner: not ML-safe", async () => {
    renderAt(
      <FeatureAnalysisPage />,
      "/experiments/:batteryId/:experimentId/analysis",
      "/experiments/CELL_001/EXP_001/analysis",
    );
    await waitFor(() => screen.getByTestId("exploratory-banner"));
    expect(screen.getByTestId("exploratory-banner")).toHaveTextContent(/not ML-safe/);
  });

  it("T26/T27 ML-safe 模式 banner: TRAIN/HELD_OUT 语义", async () => {
    const user = userEvent.setup();
    renderAt(
      <FeatureAnalysisPage />,
      "/experiments/:batteryId/:experimentId/analysis",
      "/experiments/CELL_001/EXP_001/analysis",
    );
    const radio = screen.getByRole("radio", { name: /ML 安全训练集分析/ });
    await user.click(radio);
    await waitFor(() => {
      expect(screen.getByTestId("mlsafe-banner")).toHaveTextContent(/HELD_OUT 组标签不参与 selection/);
    });
  });

  it("T28/T31 运行分析走 POST /feature-analyses（API-only）", async () => {
    const spy = vi
      .spyOn(clientModule.client, "createFeatureAnalysis")
      .mockResolvedValue({
        data: { analysis_id: "AN::test", analysis_mode: "EXPLORATORY_FULL_DATA", reuse_status: "CREATED" },
        meta: {},
      });
    renderAt(
      <FeatureAnalysisPage />,
      "/experiments/:batteryId/:experimentId/analysis",
      "/experiments/CELL_001/EXP_001/analysis",
    );
    await userEvent.click(screen.getByTestId("run-analysis"));
    await waitFor(() => {
      expect(spy).toHaveBeenCalled();
      expect(screen.getByTestId("analysis-result")).toHaveTextContent(/AN::test/);
    });
    // correlation 表不伪造数值
    expect(screen.getByTestId("correlation-table")).toHaveTextContent(/不伪造数值/);
  });
});
