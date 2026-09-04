/**
 * BRW-025R §10 — Experiment Detail 重做。
 * 高层摘要卡（Header / Pipeline Stepper / Data Summary / Readiness / Limitations top-4 /
 * Recommended Next Action 卡 / Latest Results）；ID/checksum 等退到 Advanced 折叠。
 * 只读：不发科学 POST（§52/§66）。
 */
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { client } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";
import { Badge, Card, Collapse, StatusText, Stepper } from "../design/components";

const PIPELINE_STEPS = [
  "Import", "Parse", "Sync", "Events", "Parameters",
  "Features", "Labels", "Dataset", "Split", "Model", "Report",
];

const READINESS_LABELS: Record<string, string> = {
  READY_FOR_LIMITED_EVALUATION: "SOC：就绪（有限评估）",
  READY_WITH_LIMITATIONS: "就绪（带限制）",
  BLOCKED: "受阻",
  NOT_READY_FOR_MODEL_EVALUATION: "SOH：未就绪",
};

const NEXT_ACTION_ROUTES: Record<string, string> = {
  "查看波形": "waveform",
  "resolve pending user actions": "../runs",
  "review feature selection": "analysis",
  "generate report": "reports",
  "设置参数": "overview",
  "创建闸门": "waveform",
  "分析特征": "analysis",
  "查看Dataset/Split": "dataset-split",
  "查看模型": "modeling",
  "生成报告": "reports",
};

export function ExperimentDetailPage() {
  const { batteryId = "", experimentId = "" } = useParams();
  const summary = useQuery({
    queryKey: ["workspace-summary", batteryId, experimentId],
    queryFn: () => client.getWorkspaceSummary(batteryId, experimentId),
  });
  const quality = useQuery({
    queryKey: ["data-quality", batteryId, experimentId],
    queryFn: () => client.getDataQuality(batteryId, experimentId),
  });

  if (summary.isLoading) return <StatusText>加载实验…</StatusText>;
  if (summary.error) return <ErrorBanner error={summary.error} />;
  const ws = summary.data!.data;
  const artifacts = ws.latest_canonical_artifacts ?? {};
  const readinessEntries = Object.entries(ws.readiness ?? {});
  const topLimitations = (ws.limitations_registry ?? []).slice(0, 4);

  // pipeline stepper position: derive from artifact availability (UI 展示用，非科学推导)
  let currentStep = 0;
  if (artifacts.dataset_id) currentStep = 8;
  else if (artifacts.feature_set_id) currentStep = 5;
  else if (artifacts.gate_set_id) currentStep = 4;
  else if (quality.data?.data.electrical) currentStep = 2;
  else if (ws.status === "READY_FOR_PIPELINE") currentStep = 0;

  return (
    <div data-testid="experiment-detail">
      <header style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <h2 style={{ margin: 0, flex: 1 }} data-testid="detail-name">
          {ws.experiment_id}
        </h2>
        <Badge tone="neutral">{ws.scientific_status}</Badge>
      </header>
      <p style={{ color: "var(--muted)" }}>
        <span className="mono">
          {ws.battery_id} / {ws.experiment_id}
        </span>
      </p>

      <Card title="处理流程 Pipeline" testId="pipeline-card">
        <Stepper steps={PIPELINE_STEPS} current={currentStep} />
      </Card>

      <Card title="数据摘要 Data Summary" testId="data-summary">
        {quality.data?.data ? (
          <ul>
            <li>
              Electrical：{quality.data.data.electrical
                ? `${quality.data.data.electrical.records} records / ${quality.data.data.electrical.cycles} cycles`
                : "尚未导入"}
            </li>
            <li>
              Ultrasound：{quality.data.data.ultrasound
                ? `${quality.data.data.ultrasound.frames} frames（cadence ${quality.data.data.ultrasound.frame_cadence_s ?? "—"}s；sampling_rate UNKNOWN）`
                : "尚未导入"}
            </li>
          </ul>
        ) : (
          <StatusText>加载数据摘要…</StatusText>
        )}
        <Link to="data">查看数据详情 →</Link>
      </Card>

      <Card title="科学就绪状态 Scientific Readiness（来自 API）" testId="readiness-card">
        <ul>
          {readinessEntries.map(([key, value]) => (
            <li key={key}>
              {key}: {String(value)}
              {READINESS_LABELS[String(value)] ? `（${READINESS_LABELS[String(value)]}）` : null}
            </li>
          ))}
          {readinessEntries.length === 0 ? <li>暂无就绪状态条目。</li> : null}
        </ul>
      </Card>

      <Card title="科学限制 Limitations" testId="limitations-card">
        <ul>
          {topLimitations.map((l) => (
            <li key={l.code}>
              <strong>{l.code}</strong>（{l.severity}）— {l.description}
            </li>
          ))}
        </ul>
        <Collapse summary={`查看全部 ${ws.limitations_registry.length} 条`} testId="all-limitations">
          <ul>
            {(ws.limitations_registry ?? []).slice(4).map((l) => (
              <li key={l.code}>
                <strong>{l.code}</strong>（{l.severity}）— {l.description}
              </li>
            ))}
          </ul>
        </Collapse>
      </Card>

      <Card title="建议的下一步 Recommended Next Action（来自 API）" testId="next-actions-card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {(ws.next_actions ?? []).map((a) => (
            <Link key={a} to={NEXT_ACTION_ROUTES[a] ?? "overview"}>
              <button type="button" data-testid={`next-action-${a}`}>{a}</button>
            </Link>
          ))}
        </div>
      </Card>

      <Card title="最新科研结果 Latest Results" testId="latest-results">
        <LatestResults batteryId={batteryId} experimentId={experimentId} />
      </Card>

      <Collapse summary="Advanced：artifact IDs / checksums / provenance" testId="advanced-artifacts">
        <table>
          <tbody>
            {Object.entries(artifacts).map(([k, v]) => (
              <tr key={k}>
                <td>{k}</td>
                <td className="mono">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Collapse>
    </div>
  );
}

function LatestResults({ batteryId, experimentId }: { batteryId: string; experimentId: string }) {
  const results = useQuery({
    queryKey: ["results", batteryId, experimentId],
    queryFn: () => client.getResults(batteryId, experimentId, 200),
  });
  if (results.isLoading) return <StatusText>加载结果…</StatusText>;
  if (results.error) return <ErrorBanner error={results.error} />;
  const macro = (results.data?.data ?? []).filter((r) => r.result_type === "MODEL_COMPARISON");
  if (macro.length === 0) return <p>尚无建模结果。可先运行数据导入与建模。</p>;
  const dummy = macro.find((r) => r.strategy === "DUMMY_MEAN");
  const best = macro
    .filter((r) => r.strategy !== "DUMMY_MEAN" && typeof r.value === "number")
    .sort((a, b) => (a.value as number) - (b.value as number))[0];
  const realBeats = dummy && best ? (best.value as number) < (dummy.value as number) : null;
  return (
    <div>
      <ul>
        {macro.map((r) => (
          <li key={r.result_id}>
            {r.strategy}: macro MAE {typeof r.value === "number" ? r.value.toFixed(3) : "—"}
            {r.strategy === "DUMMY_MEAN" ? "（基线）" : ""}
          </li>
        ))}
      </ul>
      {realBeats === false ? (
        <p data-testid="detail-weak-banner">
          <Badge tone="warning">诚实结论</Badge>{" "}
          <small>
            评估完成；预测优势未被证明（Best by Macro MAE: Dummy Mean）。
          </small>
        </p>
      ) : null}
      <Link to="modeling">查看建模详情 →</Link>
    </div>
  );
}
