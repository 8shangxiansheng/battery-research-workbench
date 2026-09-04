/**
 * BRW-025R V2 AppShell（§19）：一级导航按科研生命周期分组。
 * 实验库为首页；实验级页面挂在 /experiments/:batteryId/:experimentId/*。
 */
import { useQuery } from "@tanstack/react-query";
import { NavLink, Route, Routes, useParams } from "react-router-dom";
import { client } from "../api/client";
import { Badge } from "../design/components";
import { tokens } from "../design/tokens";
import { DatasetSplitPage } from "./DatasetSplitPage";
import { ExperimentLibraryPage } from "./LibraryPage";
import { NewExperimentWizardPage } from "./NewExperimentWizardPage";
import { DataWorkspacePage } from "./DataWorkspacePage";
import { ExperimentDetailPage } from "./ExperimentDetailPage";
import { FeatureAnalysisPage } from "./FeatureAnalysisPage";
import { FeaturesPage } from "./FeaturesPage";
import { ModelingPage } from "./ModelingPage";
import { ReportsPage, EvidencePage } from "./ReportsEvidencePage";
import { RunsPage } from "./RunsPage";
import { WaveformPage } from "./WaveformPage";
import { WorkspacePage } from "./WorkspacePage";

const NAV_GROUPS: { group: string; items: { path: string; label: string }[] }[] = [
  {
    group: "实验",
    items: [{ path: "overview", label: "实验总览" }],
  },
  {
    group: "数据",
    items: [{ path: "data", label: "数据 Data" }],
  },
  {
    group: "超声",
    items: [
      { path: "waveform", label: "波形与闸门" },
      { path: "features", label: "特征" },
    ],
  },
  {
    group: "分析",
    items: [
      { path: "analysis", label: "特征分析" },
      { path: "dataset-split", label: "数据集与划分" },
    ],
  },
  {
    group: "评估",
    items: [{ path: "modeling", label: "SOC 建模" }],
  },
  {
    group: "结果",
    items: [
      { path: "reports", label: "科学报告" },
      { path: "evidence", label: "证据与数据血缘" },
    ],
  },
];

function ExperimentContextHeader() {
  const { batteryId = "", experimentId = "" } = useParams();
  const lib = useQuery({
    queryKey: ["library-entry", batteryId, experimentId],
    queryFn: () => client.listLibraryExperiments({ limit: 200 }),
    staleTime: 30_000,
  });
  const entry = (lib.data?.data.experiments ?? []).find(
    (e) => e.battery_id === batteryId && e.experiment_id === experimentId,
  );
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => client.listRuns(5), refetchInterval: 10_000 });
  const latest = runs.data?.data.runs[0];
  return (
    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
      <strong className="mono" data-testid="ctx-experiment">
        {batteryId}/{experimentId}
      </strong>
      {entry?.is_demo ? <Badge tone="info">Demo</Badge> : null}
      {entry ? <Badge tone="neutral">{entry.status}</Badge> : null}
      {latest ? <Badge tone="neutral">最近运行: {latest.status}</Badge> : null}
    </div>
  );
}

function ExperimentLayout({ children }: { children: React.ReactNode }) {
  const { batteryId = "", experimentId = "" } = useParams();
  return (
    <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", minHeight: "100vh" }}>
      <header
        style={{
          gridColumn: "1 / 3",
          background: tokens.color.primary,
          color: "#fff",
          padding: "8px 16px",
          display: "flex",
          gap: 12,
          alignItems: "center",
        }}
      >
        <NavLink to="/" style={{ color: "#fff", textDecoration: "none", fontWeight: 600 }}>
          电池科研工作台
        </NavLink>
        <ExperimentContextHeader />
      </header>
      <nav aria-label="主导航" style={{ background: tokens.color.background, padding: 8, borderRight: `1px solid ${tokens.color.border}` }}>
        {NAV_GROUPS.map((g) => (
          <div key={g.group} style={{ marginBottom: 10 }}>
            <div style={{ fontSize: tokens.fontSize.sm, color: tokens.color.muted, padding: "2px 8px" }}>{g.group}</div>
            {g.items.map((item) => (
              <NavLink
                key={item.path}
                to={`/experiments/${batteryId}/${experimentId}/${item.path}`}
                style={({ isActive }) => ({
                  display: "block",
                  padding: "5px 10px",
                  borderRadius: tokens.radius.sm,
                  textDecoration: "none",
                  color: isActive ? tokens.color.primary : tokens.color.text,
                  background: isActive ? tokens.color.primarySoft : "transparent",
                })}
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        ))}
        <div style={{ borderTop: `1px solid ${tokens.color.border}`, margin: "8px 0", paddingTop: 8 }}>
          <NavLink
            to="/runs"
            style={{ display: "block", padding: "5px 10px", borderRadius: tokens.radius.sm, textDecoration: "none", color: tokens.color.text }}
          >
            运行 Runs
          </NavLink>
        </div>
      </nav>
      <main style={{ padding: 16, maxWidth: 1200 }}>{children}</main>
    </div>
  );
}

export function V2AppShell() {
  return (
    <Routes>
      <Route path="/" element={<LibraryHome />} />
      <Route path="/new" element={<WizardEntry />} />
      <Route path="/new/:sessionId" element={<WizardEntry />} />
      <Route path="/runs" element={<RunsPage />} />
      <Route
        path="/experiments/:batteryId/:experimentId/*"
        element={
          <ExperimentLayout>
            <Routes>
              <Route path="overview" element={<ExperimentDetailPage />} />
              <Route path="workspace" element={<WorkspacePage />} />
              <Route path="data" element={<DataWorkspacePage />} />
              <Route path="waveform" element={<WaveformPage />} />
              <Route path="features" element={<FeaturesPage />} />
              <Route path="analysis" element={<FeatureAnalysisPage />} />
              <Route path="dataset-split" element={<DatasetSplitPage />} />
              <Route path="modeling" element={<ModelingPage />} />
              <Route path="reports" element={<ReportsPage />} />
              <Route path="evidence" element={<EvidencePage />} />
              <Route path="*" element={<ExperimentDetailPage />} />
            </Routes>
          </ExperimentLayout>
        }
      />
    </Routes>
  );

  function LibraryHome() {
    return <ExperimentLibraryPage />;
  }
  function WizardEntry() {
    return <NewExperimentWizardPage />;
  }
}
