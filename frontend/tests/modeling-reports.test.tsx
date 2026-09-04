/** BRW-025 §63-64, §66: modeling/reporting/read-only/E2E tests。 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as clientModule from "../src/api/client";
import type { ResultRecord } from "../src/api/client";
import { ModelingPage } from "../src/pages/ModelingPage";
import { ReportsPage, EvidencePage } from "../src/pages/ReportsEvidencePage";

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

function metric(strategy: string, fold: number, kind: string, value: number): ResultRecord {
  return {
    result_id: `R::model_${strategy}_f${fold}_${kind}`,
    result_type: "MODEL_METRIC",
    name: `${strategy} fold${fold} ${kind}`,
    value,
    units: kind === "MAE" ? "percent" : "",
    scope: `fold:${fold}`,
    source_artifact_id: "MODEL::x",
    source_run_id: null,
    dataset_id: "DS::x",
    split_id: "SPLIT::x",
    model_id: "MODEL::x",
    model_family: strategy,
    evidence_type: "DIRECT_CURRENT_ARTIFACT",
    evidence_ref: "model_comparison.parquet",
    fold_index: fold,
    strategy,
    scientific_status: "",
    limitations: [],
    pooled_rows_usage: "",
  };
}

const results: ResultRecord[] = [
  metric("DUMMY_MEAN", 1, "MAE", 30.72),
  metric("RIDGE", 1, "MAE", 32.69),
  metric("DUMMY_MEAN", 2, "MAE", 28.49),
  metric("RIDGE", 2, "MAE", 29.05),
  {
    result_id: "R::macro_DUMMY_MEAN_MAE",
    result_type: "MODEL_COMPARISON",
    name: "DUMMY_MEAN macro MAE",
    value: 29.61,
    units: "percent",
    scope: "experiment",
    source_artifact_id: null,
    source_run_id: null,
    dataset_id: "DS::x",
    split_id: "SPLIT::x",
    model_id: null,
    model_family: "DUMMY_MEAN",
    evidence_type: "DIRECT_CURRENT_ARTIFACT",
    evidence_ref: "model_comparison.json",
    fold_index: null,
    strategy: "DUMMY_MEAN",
    scientific_status: "",
    limitations: [],
    pooled_rows_usage: "",
  },
  {
    result_id: "R::macro_RIDGE_MAE",
    result_type: "MODEL_COMPARISON",
    name: "RIDGE macro MAE",
    value: 30.87,
    units: "percent",
    scope: "experiment",
    source_artifact_id: null,
    source_run_id: null,
    dataset_id: "DS::x",
    split_id: "SPLIT::x",
    model_id: null,
    model_family: "RIDGE",
    evidence_type: "DIRECT_CURRENT_ARTIFACT",
    evidence_ref: "model_comparison.json",
    fold_index: null,
    strategy: "RIDGE",
    scientific_status: "",
    limitations: [],
    pooled_rows_usage: "",
  },
];

describe("ModelingPage（§64 T37-T42）", () => {
  beforeEach(() => vi.restoreAllMocks());

  function setup() {
    vi.spyOn(clientModule.client, "getResults").mockResolvedValue({ data: results, meta: {} });
  }

  it("T37 Dummy 可见且突出（高亮基线）", async () => {
    setup();
    renderAt(<ModelingPage />, "/experiments/:batteryId/:experimentId/modeling", "/experiments/CELL_001/EXP_001/modeling");
    await waitFor(() => screen.getByTestId("macro-table"));
    const dummyRow = screen.getByTestId("macro-DUMMY_MEAN");
    expect(dummyRow).toBeInTheDocument();
    expect(dummyRow).toHaveStyle({ background: "#fff8e0" });
  });

  it("T38 per-fold 指标渲染", async () => {
    setup();
    renderAt(<ModelingPage />, "/experiments/:batteryId/:experimentId/modeling", "/experiments/CELL_001/EXP_001/modeling");
    await waitFor(() => screen.getByTestId("fold-table"));
    expect(screen.getByTestId("fold-RIDGE-1")).toBeInTheDocument();
    expect(screen.getByTestId("fold-DUMMY_MEAN-2")).toBeInTheDocument();
  });

  it("T39 macro 指标渲染", async () => {
    setup();
    renderAt(<ModelingPage />, "/experiments/:batteryId/:experimentId/modeling", "/experiments/CELL_001/EXP_001/modeling");
    await waitFor(() => screen.getByTestId("macro-table"));
    expect(screen.getByTestId("macro-RIDGE")).toHaveTextContent("30.870");
  });

  it("T40 弱结果诚实措辞（不是 Model Failed）", async () => {
    setup();
    renderAt(<ModelingPage />, "/experiments/:batteryId/:experimentId/modeling", "/experiments/CELL_001/EXP_001/modeling");
    await waitFor(() => screen.getByTestId("weak-result-banner"));
    expect(screen.getByTestId("weak-result-banner")).toHaveTextContent(/预测优势未被证明/);
    expect(screen.getByTestId("weak-result-banner")).toHaveTextContent(/evaluation complete/);
  });

  it("T42 无 tuning 控件", async () => {
    setup();
    renderAt(<ModelingPage />, "/experiments/:batteryId/:experimentId/modeling", "/experiments/CELL_001/EXP_001/modeling");
    await waitFor(() => screen.getByTestId("macro-table"));
    // 无 tuning 控件（无输入/按钮），只有说明文字
    expect(screen.queryByRole("button", { name: /tuning|调参|网格搜索/ })).toBeNull();
    expect(document.querySelectorAll("input[type=number]").length).toBe(0);
  });
});

describe("ReportsPage / EvidencePage（§65 T43-T48）", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("T43/T44 生成报告（reuse 显示）", async () => {
    const user = userEvent.setup();
    const spy = vi
      .spyOn(clientModule.client, "createReport")
      .mockResolvedValue({
        data: { report_id: "REPORT::abc", reuse_status: "REUSED", limitations: [] },
        meta: {},
      });
    vi.spyOn(clientModule.client, "listReports").mockResolvedValue({ data: [], meta: {} });
    renderAt(<ReportsPage />, "/experiments/:batteryId/:experimentId/reports", "/experiments/CELL_001/EXP_001/reports");
    await user.click(await screen.findByTestId("generate-report"));
    await waitFor(() => {
      expect(spy).toHaveBeenCalled();
      expect(screen.getByTestId("report-created")).toHaveTextContent(/REUSED/);
    });
  });

  it("T45/T46 证据面板：等级标签 + 视觉区分（class 属性）", async () => {
    vi.spyOn(clientModule.client, "getEvidence").mockResolvedValue({
      data: {
        evidence: [
          { evidence_type: "DIRECT_CURRENT_ARTIFACT", evidence_ref: "model_comparison.json", artifact_id: null, artifact_availability: "AVAILABLE" },
          { evidence_type: "PRIOR_AUDIT", evidence_ref: "audit_2024.json", artifact_id: null, artifact_availability: "NOT_AVAILABLE_CURRENT_ENVIRONMENT" },
        ],
      },
      meta: {},
    });
    vi.spyOn(clientModule.client, "getLimitations").mockResolvedValue({
      data: { limitations: [{ code: "ONE_BATTERY_ONLY", severity: "BLOCKING_FOR_CLAIM", description: "x" }] },
      meta: {},
    });
    vi.spyOn(clientModule.client, "getLineage").mockResolvedValue({
      data: { battery_id: "CELL_001", experiment_id: "EXP_001", lineage_chain: [] },
      meta: {},
    });
    renderAt(<EvidencePage />, "/experiments/:batteryId/:experimentId/evidence", "/experiments/CELL_001/EXP_001/evidence");
    await waitFor(() => screen.getByTestId("evidence-table"));
    const direct = screen.getByTestId("evidence-DIRECT_CURRENT_ARTIFACT");
    const prior = screen.getByTestId("evidence-PRIOR_AUDIT");
    expect(direct).toHaveTextContent(/直接当前产物/);
    expect(prior).toHaveTextContent(/既往审计/);
    // 视觉区分：不同 class 的背景样式不同
    expect(getComputedStyle(direct).background).not.toBe(getComputedStyle(prior).background);
  });

  it("T47 lineage stepper 渲染", async () => {
    vi.spyOn(clientModule.client, "getEvidence").mockResolvedValue({ data: { evidence: [] }, meta: {} });
    vi.spyOn(clientModule.client, "getLimitations").mockResolvedValue({ data: { limitations: [] }, meta: {} });
    vi.spyOn(clientModule.client, "getLineage").mockResolvedValue({
      data: {
        battery_id: "CELL_001",
        experiment_id: "EXP_001",
        lineage_chain: [
          { artifact_type: "DATASET", artifact_id: "DS::abc", status: "AVAILABLE" },
          { artifact_type: "SPLIT", artifact_id: null, status: "NOT_AVAILABLE" },
        ],
      },
      meta: {},
    });
    renderAt(<EvidencePage />, "/experiments/:batteryId/:experimentId/evidence", "/experiments/CELL_001/EXP_001/evidence");
    await waitFor(() => screen.getByTestId("lineage-chain"));
    expect(screen.getByTestId("lineage-chain")).toHaveTextContent(/DS::abc/);
    expect(screen.getByText(/（不可用）/)).toBeInTheDocument();
  });
});

describe("Read-only（§66 T49-T52）+ URL（§50）", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("T49/T50 打开只读页面不发 POST", async () => {
    const postSpies = [
      vi.spyOn(clientModule.client, "createDataset"),
      vi.spyOn(clientModule.client, "createSplit"),
      vi.spyOn(clientModule.client, "createBaselineModel"),
      vi.spyOn(clientModule.client, "createReport"),
      vi.spyOn(clientModule.client, "createFeatureAnalysis"),
      vi.spyOn(clientModule.client, "startRun"),
    ];
    vi.spyOn(clientModule.client, "getWorkspaceSummary").mockResolvedValue({
      data: {
        battery_id: "CELL_001", experiment_id: "EXP_001", experiment_composite_id: "CELL_001/EXP_001",
        scientific_status: "READY", limitations: [], latest_canonical_artifacts: {}, run_ids: [],
        limitations_registry: [], readiness: {}, next_actions: [],
        dataset_id: null, split_id: null, label_set_id: null, gate_set_id: null, feature_set_id: null,
      },
      meta: {},
    });
    vi.spyOn(clientModule.client, "listReports").mockResolvedValue({ data: [], meta: {} });
    renderAt(<ReportsPage />, "/experiments/:batteryId/:experimentId/reports", "/experiments/CELL_001/EXP_001/reports");
    await waitFor(() => screen.getByTestId("no-reports"));
    for (const spy of postSpies) {
      expect(spy).not.toHaveBeenCalled();
    }
  });
});
