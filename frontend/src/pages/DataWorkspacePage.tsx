/**
 * BRW-025R §11 — Data Workspace：Assets / Data Quality / Synchronization / MeasurementEvents。
 * 只读聚合，无重算；Events 分页（§37）。
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { client } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";
import { Badge, Card, StatusText } from "../design/components";

const TABS = ["Assets", "Data Quality", "Synchronization", "MeasurementEvents"] as const;
type Tab = (typeof TABS)[number];

export function DataWorkspacePage() {
  const { batteryId = "", experimentId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("Assets");
  const [eventsCursor, setEventsCursor] = useState<number | undefined>(undefined);

  const assets = useQuery({
    queryKey: ["exp-assets", batteryId, experimentId],
    queryFn: () => client.listExperimentAssets(batteryId, experimentId),
  });
  const quality = useQuery({
    queryKey: ["data-quality", batteryId, experimentId],
    queryFn: () => client.getDataQuality(batteryId, experimentId),
  });
  const sync = useQuery({
    queryKey: ["sync", batteryId, experimentId],
    queryFn: () => client.getSynchronization(batteryId, experimentId),
  });
  const events = useQuery({
    queryKey: ["events", batteryId, experimentId, eventsCursor],
    queryFn: () => client.getMeasurementEvents(batteryId, experimentId, 20, eventsCursor),
    enabled: tab === "MeasurementEvents",
  });

  return (
    <div data-testid="data-workspace">
      <h2>数据 Data</h2>
      <div role="tablist" aria-label="数据视图" style={{ display: "flex", gap: 4, marginBottom: 12 }}>
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            type="button"
            aria-selected={tab === t}
            data-testid={`tab-${t.replace(/ /g, "-")}`}
            style={{
              background: tab === t ? "var(--primary-soft)" : "var(--surface)",
              borderColor: tab === t ? "var(--primary)" : "var(--border)",
            }}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Assets" && (
        <Card title="资产 Assets（role / adapter / checksum / filename）" testId="assets-tab">
          {assets.isLoading ? (
            <StatusText>加载资产…</StatusText>
          ) : assets.error ? (
            <ErrorBanner error={assets.error} />
          ) : (assets.data?.data.assets.length ?? 0) === 0 ? (
            <p>暂无已提交资产。</p>
          ) : (
            <table data-testid="assets-table">
              <thead>
                <tr>
                  <th>asset_id</th>
                  <th>modality/role</th>
                  <th>adapter</th>
                  <th>filename</th>
                  <th>sha256（短）</th>
                </tr>
              </thead>
              <tbody>
                {(assets.data?.data.assets ?? []).map((a) => (
                  <tr key={String(a.asset_id)}>
                    <td className="mono">{String(a.asset_id)}</td>
                    <td>{String(a.modality)}</td>
                    <td>{String(a.parser_name ?? "—")}</td>
                    <td className="mono">{String(a.relative_path).split("/").pop()}</td>
                    <td className="mono">{a.sha256 ? String(a.sha256).slice(0, 12) + "…" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}

      {tab === "Data Quality" && (
        <Card title="数据质量 Data Quality（API 聚合，前端不重算）" testId="quality-tab">
          {quality.isLoading ? (
            <StatusText>加载…</StatusText>
          ) : quality.error ? (
            <ErrorBanner error={quality.error} />
          ) : quality.data?.data ? (
            <div data-testid="quality-content">
              {quality.data.data.electrical ? (
                <ul>
                  <li>Electrical records: {quality.data.data.electrical.records}</li>
                  <li>Cycles: {quality.data.data.electrical.cycles ?? "—"}</li>
                  <li>Steps: {quality.data.data.electrical.steps ?? "—"}</li>
                  <li>重复时间戳: {quality.data.data.electrical.duplicate_timestamps ?? "—"}</li>
                </ul>
              ) : (
                <p>Electrical 数据尚未导入。</p>
              )}
              {quality.data.data.ultrasound ? (
                <ul>
                  <li>Ultrasound frames: {quality.data.data.ultrasound.frames}</li>
                  <li>Frame cadence: {quality.data.data.ultrasound.frame_cadence_s ?? "—"} s</li>
                  <li>
                    sampling_rate_hz: <Badge tone="warning">UNKNOWN</Badge>{" "}
                    <small>{quality.data.data.ultrasound.note}</small>
                  </li>
                </ul>
              ) : (
                <p>Ultrasound 数据尚未导入。</p>
              )}
            </div>
          ) : null}
        </Card>
      )}

      {tab === "Synchronization" && (
        <Card title="同步 Synchronization（PROVISIONAL ≠ 软件错误 — §11）" testId="sync-tab">
          {sync.isLoading ? (
            <StatusText>加载…</StatusText>
          ) : sync.error ? (
            <ErrorBanner error={sync.error} />
          ) : sync.data?.data ? (
            <div data-testid="sync-content">
              <ul>
                <li>
                  match_state: <Badge tone={sync.data.data.match_state === "MATCHED_UNIQUE" ? "success" : "warning"}>{sync.data.data.match_state}</Badge>
                </li>
                <li>matched frames: {sync.data.data.matches_frames ?? "—"}</li>
                <li>ambiguous frames: {(sync.data.data.ambiguous_frames as unknown[]).length}</li>
                <li>sync tolerance: {sync.data.data.sync_tolerance_s ?? "—"} s</li>
                <li>
                  validated_sync: <strong>{String(sync.data.data.validated_sync)}</strong>
                </li>
                <li>
                  timebase: <Badge tone="info">{sync.data.data.timebase_status}</Badge>
                </li>
              </ul>
              <p>
                <small>{sync.data.data.note}</small>
              </p>
            </div>
          ) : null}
        </Card>
      )}

      {tab === "MeasurementEvents" && (
        <Card title="测量事件 MeasurementEvents（分页预览）" testId="events-tab">
          {events.isLoading ? (
            <StatusText>加载…</StatusText>
          ) : events.error ? (
            <ErrorBanner error={events.error} />
          ) : events.data?.data ? (
            <div data-testid="events-content">
              <p>
                共 {events.data.data.total} 条{eventsCursor ? `（从 #${eventsCursor} 起）` : ""}
              </p>
              <table>
                <thead>
                  <tr>
                    <th>event_id</th>
                    <th>frame</th>
                    <th>timestamp</th>
                    <th>cycle</th>
                    <th>step</th>
                    <th>voltage</th>
                    <th>current</th>
                    <th>SOC</th>
                  </tr>
                </thead>
                <tbody>
                  {events.data.data.events.map((e) => (
                    <tr key={e.measurement_event_id}>
                      <td className="mono">{e.measurement_event_id.slice(0, 14)}…</td>
                      <td>{e.frame_index_raw ?? "—"}</td>
                      <td>
                        <small>{e.timestamp ?? "—"}</small>
                      </td>
                      <td>{e.cycle_index_raw ?? "—"}</td>
                      <td>{e.step_index_raw ?? "—"}</td>
                      <td>{e.voltage_v ?? "—"}</td>
                      <td>{e.current_a ?? "—"}</td>
                      <td>{e.soc_reference_percent ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ marginTop: 8 }}>
                {eventsCursor !== undefined && eventsCursor > 0 ? (
                  <button type="button" onClick={() => setEventsCursor(undefined)}>
                    ← 首页
                  </button>
                ) : null}{" "}
                {events.data.meta &&
                typeof (events.data.meta as { next_cursor?: number }).next_cursor === "number" ? (
                  <button
                    type="button"
                    data-testid="events-next"
                    onClick={() =>
                      setEventsCursor((events.data!.meta as { next_cursor: number }).next_cursor)
                    }
                  >
                    下一页 →
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}
        </Card>
      )}
    </div>
  );
}
