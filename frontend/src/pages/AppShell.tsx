/**
 * BRW-025 App shell（§48）：Top bar（experiment selector / run status / pending actions）
 * + 左侧导航 + 主工作区。简体中文；科研工程桌面风格（§47）。
 * URL state：experiment/page 参数可刷新恢复（§50）。
 */
import { useQuery } from "@tanstack/react-query";
import { NavLink, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { client } from "../api/client";
import { DatasetSplitPage } from "./DatasetSplitPage";
import { FeatureAnalysisPage } from "./FeatureAnalysisPage";
import { FeaturesPage } from "./FeaturesPage";
import { ModelingPage } from "./ModelingPage";
import { ReportsPage, EvidencePage } from "./ReportsEvidencePage";
import { RunsPage } from "./RunsPage";
import { WaveformPage } from "./WaveformPage";
import { WorkspacePage } from "./WorkspacePage";

const NAV_ITEMS = [
  { path: "workspace", label: "工作区 Workspace" },
  { path: "waveform", label: "波形与闸门 Waveform & Gates" },
  { path: "features", label: "特征 Features" },
  { path: "analysis", label: "特征分析 Feature Analysis" },
  { path: "dataset-split", label: "数据集与划分 Dataset & Split" },
  { path: "modeling", label: "SOC 建模 Modeling" },
  { path: "reports", label: "科学报告 Reports" },
  { path: "evidence", label: "证据与血缘 Evidence & Lineage" },
  { path: "runs", label: "运行记录 Runs" },
] as const;

function ExperimentSelector() {
  const { batteryId = "", experimentId = "" } = useParams();
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["experiments"], queryFn: () => client.listExperiments() });
  const experiments = data?.data ?? [];
  const current = `${batteryId}/${experimentId}`;

  return (
    <label style={{ color: "#fff" }}>
      实验 Experiment:{" "}
      <select
        data-testid="experiment-selector"
        value={current}
        onChange={(e) => {
          const [b, exp] = e.target.value.split("/");
          void navigate(`/experiments/${b}/${exp}/workspace`);
        }}
      >
        {experiments.length === 0 ? <option value={current}>{current || "（无）"}</option> : null}
        {experiments.map((e) => (
          <option key={e.experiment_composite_id} value={e.experiment_composite_id}>
            {e.experiment_composite_id}
          </option>
        ))}
      </select>
    </label>
  );
}

export function AppShell() {
  const { batteryId = "CELL_001", experimentId = "EXP_001" } = useParams();
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => client.listRuns(5),
    refetchInterval: 10000,
  });
  const latestRuns = runs.data?.data.runs ?? [];
  const waitingCount = latestRuns.filter((r) => r.status === "WAITING_FOR_USER").length;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", minHeight: "100vh" }}>
      <header
        style={{
          gridColumn: "1 / 3",
          background: "#2a3b4d",
          color: "#fff",
          padding: "0.5rem 1rem",
          display: "flex",
          gap: "1rem",
          alignItems: "center",
        }}
      >
        <strong>电池科研工作台</strong>
        <ExperimentSelector />
        <span data-testid="run-status-chip" style={{ marginLeft: "auto" }}>
          运行: {latestRuns.length > 0 ? latestRuns[0]?.status : "无"}
        </span>
        {waitingCount > 0 ? (
          <span data-testid="pending-actions-chip" style={{ background: "#d82", padding: "0 0.4rem", borderRadius: 3 }}>
            {waitingCount} 个待处理动作
          </span>
        ) : null}
      </header>

      <nav aria-label="主导航" style={{ background: "#f0f2f4", padding: "0.5rem" }}>
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {NAV_ITEMS.map((item) => (
            <li key={item.path} style={{ margin: "0.2rem 0" }}>
              <NavLink
                to={`/experiments/${batteryId}/${experimentId}/${item.path}`}
                style={({ isActive }) => ({
                  display: "block",
                  padding: "0.4rem 0.6rem",
                  borderRadius: 4,
                  background: isActive ? "#d6e4f0" : "transparent",
                  color: "#1a2a3a",
                  textDecoration: "none",
                })}
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <main style={{ padding: "1rem" }}>
        <Routes>
          <Route path="workspace" element={<WorkspacePage />} />
          <Route path="waveform" element={<WaveformPage />} />
          <Route path="features" element={<FeaturesPage />} />
          <Route path="analysis" element={<FeatureAnalysisPage />} />
          <Route path="dataset-split" element={<DatasetSplitPage />} />
          <Route path="modeling" element={<ModelingPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="evidence" element={<EvidencePage />} />
          <Route path="runs" element={<RunsPage />} />
          <Route path="*" element={<WorkspacePage />} />
        </Routes>
      </main>
    </div>
  );
}
