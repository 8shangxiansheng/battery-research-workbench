/**
 * 科学报告 + 证据与血缘（§36-40）。
 * 报告请求聚合 only（不 refit）；数值→证据→限制可追溯；证据等级视觉区分（§39）。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { client, type EvidenceEntry, type LineageNode } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";

export const EVIDENCE_CLASS_LABELS: Record<string, string> = {
  DIRECT_CURRENT_ARTIFACT: "直接当前产物（Direct Current Artifact）",
  PRIOR_AUDIT: "既往审计（Prior Audit）",
  SYNTHETIC_TEST: "合成测试（Synthetic Test）",
  SOURCE_INFERENCE: "源代码推断（Source Inference）",
  DERIVED_COMPUTATION: "派生计算（Derived Computation）",
  USER_PROVIDED_CONTEXT: "用户提供（User Provided）",
  BLOCKED: "受阻（Blocked）",
  UNAVAILABLE: "不可用（Unavailable）",
};

const EVIDENCE_CLASS_STYLE: Record<string, { background: string; border: string }> = {
  DIRECT_CURRENT_ARTIFACT: { background: "#eef6ee", border: "1px solid #4a4" },
  PRIOR_AUDIT: { background: "#fdf6ec", border: "1px solid #c90" },
  SYNTHETIC_TEST: { background: "#eef", border: "1px solid #66a" },
  SOURCE_INFERENCE: { background: "#f4f0f8", border: "1px solid #86a" },
};

export function EvidenceTag({ evidence }: { evidence: EvidenceEntry }) {
  const style = EVIDENCE_CLASS_STYLE[evidence.evidence_type] ?? {
    background: "#f5f5f5",
    border: "1px solid #999",
  };
  return (
    <span
      data-testid={`evidence-${evidence.evidence_type}`}
      style={{ ...style, padding: "0.1rem 0.4rem", borderRadius: 3, fontSize: "0.85em" }}
    >
      {EVIDENCE_CLASS_LABELS[evidence.evidence_type] ?? evidence.evidence_type}
    </span>
  );
}

export function ReportsPage() {
  const { batteryId = "", experimentId = "" } = useParams();
  const [created, setCreated] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const qc = useQueryClient();

  const reports = useQuery({
    queryKey: ["reports", batteryId, experimentId],
    queryFn: () => client.listReports(batteryId, experimentId),
  });

  const generate = useMutation({
    mutationFn: () =>
      client.createReport({ battery_id: batteryId, experiment_id: experimentId }),
    onSuccess: (r) => {
      setCreated(r.data);
      void qc.invalidateQueries({ queryKey: ["reports"] });
    },
    onError: (e) => setError(e),
  });

  const reportList = (reports.data?.data ?? []) as Record<string, unknown>[];

  return (
    <section aria-labelledby="reports-title">
      <h2 id="reports-title">科学报告 Reports</h2>
      <p>
        <small>
          报告生成 = 聚合既有产物（BRW-023 aggregation-only），不触发模型 refit（§36/§52）。
        </small>
      </p>
      <button
        type="button"
        data-testid="generate-report"
        disabled={generate.isPending}
        onClick={() => {
          setError(null);
          generate.mutate();
        }}
      >
        {generate.isPending ? "生成中…" : "生成报告（POST /reports）"}
      </button>
      {created ? (
        <p data-testid="report-created">
          report_id: <code>{String(created.report_id)}</code> —{" "}
          <strong>{String(created.reuse_status)}</strong>
        </p>
      ) : null}
      {error ? <ErrorBanner error={error} /> : null}

      <h3>报告列表</h3>
      {reports.isLoading ? (
        <p role="status">加载报告列表…</p>
      ) : reports.error ? (
        <ErrorBanner error={reports.error} />
      ) : reportList.length === 0 ? (
        <p data-testid="no-reports">暂无报告记录（生成后会出现在此处）。</p>
      ) : (
        <ul data-testid="report-list">
          {reportList.map((r) => (
            <li key={String(r.report_id)}>
              <code>{String(r.report_id)}</code> · target: {String(r.target ?? "—")}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function EvidencePage() {
  const { batteryId = "", experimentId = "" } = useParams();
  const evidence = useQuery({
    queryKey: ["evidence", batteryId, experimentId],
    queryFn: () => client.getEvidence(batteryId, experimentId),
  });
  const limitations = useQuery({
    queryKey: ["limitations", batteryId, experimentId],
    queryFn: () => client.getLimitations(batteryId, experimentId),
  });
  const lineage = useQuery({
    queryKey: ["lineage", batteryId, experimentId],
    queryFn: () => client.getLineage(batteryId, experimentId),
  });

  if (evidence.isLoading || limitations.isLoading || lineage.isLoading)
    return <p role="status">加载证据/限制/血缘…</p>;
  if (evidence.error) return <ErrorBanner error={evidence.error} />;

  const entries = evidence.data?.data.evidence ?? [];
  const lims = limitations.data?.data.limitations ?? [];
  const chain: LineageNode[] = lineage.data?.data.lineage_chain ?? [];

  return (
    <section aria-labelledby="evidence-title">
      <h2 id="evidence-title">证据与血缘 Evidence &amp; Lineage</h2>

      <h3>证据注册表（等级视觉区分 — §39）</h3>
      <table data-testid="evidence-table">
        <thead>
          <tr>
            <th>等级</th>
            <th>evidence_ref</th>
            <th>artifact_id</th>
            <th>availability</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
            <tr key={`${e.evidence_ref}-${i}`}>
              <td>
                <EvidenceTag evidence={e} />
              </td>
              <td>
                <code>{e.evidence_ref}</code>
              </td>
              <td>{e.artifact_id ? <code>{e.artifact_id}</code> : "—"}</td>
              <td>{e.artifact_availability}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>科学限制（限制 drill-down — T48）</h3>
      <ul data-testid="limitations-drilldown">
        {lims.map((l) => (
          <li key={l.code}>
            <strong>{l.code}</strong>（{l.severity}）— {l.description}
          </li>
        ))}
      </ul>

      <h3>血缘 Lineage（stepper — §40）</h3>
      <ol data-testid="lineage-chain">
        {chain.map((n) => (
          <li key={n.artifact_type}>
            {n.artifact_type}: {n.artifact_id ? <code>{n.artifact_id}</code> : "（不可用）"}{" "}
            [{n.status}]
          </li>
        ))}
      </ol>
    </section>
  );
}
