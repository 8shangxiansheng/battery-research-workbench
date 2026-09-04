/**
 * BRW-025R §2 — Experiment Library 首页。
 * 搜索/状态过滤/Demo过滤/分页 + 新建实验 + 加载 Demo + 空态。
 * CELL_001/EXP_001 只是 Demo（badge 标记，§22）。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { client } from "../api/client";
import { Badge, EmptyState, StatusText } from "../design/components";
import { tokens } from "../design/tokens";
import { ErrorBanner } from "../components/ErrorBanner";

const STATUS_LABELS: Record<string, string> = {
  DRAFT: "草稿",
  AWAITING_DATA: "等待数据",
  IMPORTING: "导入中",
  IMPORT_VALIDATION_REQUIRED: "待验证",
  READY_FOR_PIPELINE: "就绪可跑",
  WAITING_FOR_USER: "等待用户",
  RUNNING: "运行中",
  READY: "就绪",
  FAILED: "失败",
  ARCHIVED: "已归档",
};

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "READY" || status === "READY_FOR_PIPELINE"
      ? "success"
      : status === "FAILED"
        ? "blocked"
        : status === "RUNNING" || status === "WAITING_FOR_USER"
          ? "warning"
          : "neutral";
  return <Badge tone={tone}>{STATUS_LABELS[status] ?? status}</Badge>;
}

export function ExperimentLibraryPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [demoFilter, setDemoFilter] = useState<"" | "true" | "false">("");
  const [actionError, setActionError] = useState<unknown>(null);

  const library = useQuery({
    queryKey: ["library", statusFilter, demoFilter],
    queryFn: () =>
      client.listLibraryExperiments({
        limit: 100,
        status: statusFilter || undefined,
        is_demo: demoFilter === "" ? undefined : demoFilter === "true",
      }),
  });

  const loadDemo = useMutation({
    mutationFn: () => client.loadDemo("CELL_001", "EXP_001"),
    onSuccess: () => {
      setActionError(null);
      void qc.invalidateQueries({ queryKey: ["library"] });
    },
    onError: (e) => setActionError(e),
  });

  const all = library.data?.data.experiments ?? [];
  const filtered = all.filter((e) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      e.name.toLowerCase().includes(q) ||
      e.experiment_id.toLowerCase().includes(q) ||
      e.battery_id.toLowerCase().includes(q) ||
      e.experiment_composite_id.toLowerCase().includes(q)
    );
  });

  if (library.isLoading) return <StatusText>加载实验库…</StatusText>;
  if (library.error) return <ErrorBanner error={library.error} />;

  if (all.length === 0) {
    return (
      <EmptyState
        title={<>欢迎使用 Battery Research Workbench</>}
        actions={
          <>
            <button
              type="button"
              className="primary"
              data-testid="empty-create"
              onClick={() => navigate("new")}
            >
              创建第一个实验
            </button>
            <button
              type="button"
              data-testid="empty-load-demo"
              onClick={() => loadDemo.mutate()}
              disabled={loadDemo.isPending}
            >
              {loadDemo.isPending ? "加载中…" : "加载 Demo"}
            </button>
          </>
        }
      />
    );
  }

  return (
    <section aria-labelledby="library-title">
      <header style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <h2 id="library-title" style={{ margin: 0, flex: 1 }}>
          实验库 Experiments
        </h2>
        <button
          type="button"
          className="primary"
          data-testid="new-experiment"
          onClick={() => navigate("new")}
        >
          + 新建实验
        </button>
        <button
          type="button"
          data-testid="load-demo-btn"
          onClick={() => loadDemo.mutate()}
          disabled={loadDemo.isPending}
        >
          {loadDemo.isPending ? "加载中…" : "加载 Demo"}
        </button>
      </header>

      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <label htmlFor="lib-search">
          <span style={{ color: tokens.color.muted }}>搜索：</span>
          <input
            id="lib-search"
            data-testid="library-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="名称 / ID"
          />
        </label>
        <label htmlFor="lib-status">
          <span style={{ color: tokens.color.muted }}>状态：</span>
          <select
            id="lib-status"
            data-testid="library-status-filter"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">全部</option>
            {Object.entries(STATUS_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor="lib-demo">
          <span style={{ color: tokens.color.muted }}>类型：</span>
          <select
            id="lib-demo"
            data-testid="library-demo-filter"
            value={demoFilter}
            onChange={(e) => setDemoFilter(e.target.value as "" | "true" | "false")}
          >
            <option value="">全部</option>
            <option value="false">正式实验</option>
            <option value="true">仅 Demo</option>
          </select>
        </label>
      </div>

      {actionError ? <ErrorBanner error={actionError} /> : null}

      {filtered.length === 0 ? (
        <StatusText>没有匹配的实验。</StatusText>
      ) : (
        <table data-testid="library-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>Battery / Experiment</th>
              <th>状态</th>
              <th>资产</th>
              <th>类型</th>
              <th>更新时间</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => (
              <tr key={e.experiment_composite_id} data-testid={`exp-row-${e.experiment_id}`}>
                <td>
                  <Link to={`/experiments/${e.battery_id}/${e.experiment_id}`}>
                    {e.name}
                  </Link>
                </td>
                <td className="mono">
                  {e.battery_id} / {e.experiment_id}
                </td>
                <td>
                  <StatusBadge status={e.status} />
                </td>
                <td>{e.asset_summary?.committed_assets ?? 0}</td>
                <td>{e.is_demo ? <Badge tone="info">Demo</Badge> : <Badge tone="neutral">实验</Badge>}</td>
                <td>
                  <small>{e.updated_at ? new Date(e.updated_at).toLocaleString("zh-CN") : "—"}</small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

