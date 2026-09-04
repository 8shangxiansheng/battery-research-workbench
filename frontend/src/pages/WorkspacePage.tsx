/** 工作区总览 — 只用 workspace-summary，UI 不自行推导 readiness（§6）。 */
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { client } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";

const READINESS_LABELS: Record<string, string> = {
  READY_FOR_LIMITED_EVALUATION: "就绪（有限评估）",
  BLOCKED: "受阻",
  NOT_READY_FOR_MODEL_EVALUATION: "SOH 未就绪（不适合建模评估）",
  READY_WITH_LIMITATIONS: "就绪（带限制）",
};

function readinessLabel(value: unknown): string {
  if (value === null || value === undefined) return "未知";
  const text = String(value);
  return READINESS_LABELS[text] ?? text;
}

export function WorkspacePage() {
  const { batteryId = "", experimentId = "" } = useParams();
  const { data, isLoading, error } = useQuery({
    queryKey: ["workspace-summary", batteryId, experimentId],
    queryFn: () => client.getWorkspaceSummary(batteryId, experimentId),
    // 只读页面：不发任何 POST（§52）
  });

  if (isLoading) return <p role="status">加载中…</p>;
  if (error) return <ErrorBanner error={error} />;
  const ws = data?.data;
  if (!ws) return <p role="status">无数据</p>;

  const artifacts = ws.latest_canonical_artifacts ?? {};

  return (
    <section aria-labelledby="workspace-title">
      <h2 id="workspace-title">
        工作区 Workspace — {ws.battery_id} / {ws.experiment_id}
      </h2>

      <h3>科学状态（来自 API，UI 不推导）</h3>
      <p>
        pipeline status:{" "}
        <strong data-testid="scientific-status">{ws.scientific_status}</strong>
        {READINESS_LABELS[ws.scientific_status]
          ? `（${READINESS_LABELS[ws.scientific_status]}）`
          : null}
      </p>

      <h3>最新产物（latest canonical artifacts）</h3>
      <ul data-testid="artifact-list">
        {Object.entries(artifacts).map(([key, value]) => (
          <li key={key}>
            {key}: <code>{value}</code>
          </li>
        ))}
      </ul>

      <h3>科学就绪状态（readiness）</h3>
      <ul data-testid="readiness-list">
        {Object.entries(ws.readiness ?? {}).map(([key, value]) => {
          const raw = value === null || value === undefined ? "UNKNOWN" : String(value);
          const label = readinessLabel(value);
          return (
            <li key={key}>
              {key}: {raw}
              {label !== raw ? `（${label}）` : null}
            </li>
          );
        })}
      </ul>

      <h3>科学限制（limitations）</h3>
      <ul data-testid="limitations-list">
        {(ws.limitations_registry ?? []).map((l) => (
          <li key={l.code}>
            <strong>{l.code}</strong>（{l.severity}）— {l.description}
          </li>
        ))}
      </ul>

      <h3>建议的下一步（API next_actions）</h3>
      <ul data-testid="next-actions">
        {(ws.next_actions ?? []).map((a) => (
          <li key={a}>
            <Link to={`/experiments/${batteryId}/${experimentId}/waveform`}>{a}</Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
