import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { client, type AlignmentSampleRow } from "../../api/client";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../ui/dialog";
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from "../ui/table";
import { LoadingState, ErrorState } from "./shared";
import { numberText } from "../../lib/presentation";

export function AlignmentStatusBadge() {
  return <Badge variant="outline" data-testid="alignment-status-badge">
    PROVISIONAL timebase · validated_sync=false</Badge>;
}

export function AlignmentSummary({ batteryId, experimentId, targetId }: {
  batteryId: string; experimentId: string; targetId: string | null;
}) {
  const summary = useQuery({
    queryKey: ["alignment-summary", batteryId, experimentId],
    queryFn: () => client.getAlignmentSummary(batteryId, experimentId),
  });
  if (summary.isLoading) return <LoadingState />;
  if (summary.error) return <ErrorState error={summary.error} retry={() => void summary.refetch()} />;
  const d = summary.data!.data;
  const stats = [
    { label: "Ultrasound frames / 超声帧", value: d.total_frames, testid: "align-total" },
    { label: "Matched unique / 唯一匹配", value: d.matched_unique, testid: "align-matched" },
    { label: "Ambiguous / 止义匹配", value: d.ambiguous, testid: "align-ambiguous" },
    { label: "Unmatched / 未匹配", value: d.unmatched, testid: "align-unmatched" },
    { label: "Target valid / 标签有效", value: d.target_valid[targetId ?? "reference_soc_percent"] ?? "—", testid: "align-target-valid" },
    { label: "Eligible / 可用于分析", value: d.eligible, testid: "align-eligible" },
    { label: "Excluded / 排除", value: d.excluded, testid: "align-excluded" },
  ];
  return <div data-testid="alignment-summary">
    <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
      {stats.map(s => <div key={s.label} className="feature-card !p-3">
        <p className="text-xs muted leading-snug">{s.label}</p>
        <p className="text-xl tabular-nums mt-1" data-testid={s.testid}>{typeof s.value === "number" ? numberText(s.value, 0) : s.value}</p>
      </div>)}
    </div>
    <div className="notice mt-4 items-center" data-testid="alignment-semantics">
      <div className="flex-1">
        <h3 className="flex gap-2 items-center text-sm">Synchronization semantics / 同步语义 {<AlignmentStatusBadge />}</h3>
        <p className="text-xs muted mt-1">
          使用暂定实验时间基准完成对齐 / Aligned using provisional experiment timebase — 不是完全验证同步。
          matching_performed · validated_sync=false
        </p>
        <p className="text-xs muted mt-1">
          Sync error / 同步误差: max |error| = <span className="tabular-nums">{numberText(d.sync_quality.max_sync_error_s, 4)} s</span>
          {d.sync_quality.max_sync_error_limit_s != null && <> · 允许上限 {numberText(d.sync_quality.max_sync_error_limit_s, 2)} s</>}
        </p>
        <p className="text-xs muted mt-1">
          闸门只是同一超声帧内部的局部采样窗口；该帧提取出的所有特征共享同一个 MeasurementEvent 电学状态。
          A waveform gate is a local sample region inside one ultrasound frame — all features from that frame share the same electrical context.
        </p>
      </div>
    </div>
  </div>;
}

export function AlignmentExclusionsPanel({ batteryId, experimentId }: {
  batteryId: string; experimentId: string;
}) {
  const excl = useQuery({
    queryKey: ["alignment-exclusions", batteryId, experimentId],
    queryFn: () => client.getAlignmentExclusions(batteryId, experimentId),
  });
  if (excl.isLoading) return <LoadingState />;
  if (excl.error) return <ErrorState error={excl.error} retry={() => void excl.refetch()} />;
  const groups = (excl.data?.data.exclusions ?? []).filter(e => e.count > 0 || e.reason === "AMBIGUOUS_SYNC");
  return <div data-testid="alignment-exclusions" className="mt-4">
    <h3>Excluded samples / 已排除样本</h3>
    <p className="text-xs muted mt-1">按原因聚合；歧义/未匹配行不会自动选择电学记录，选中电学身份保持为空。</p>
    <Table>
      <TableHeader><TableRow><TableHead>Reason / 原因</TableHead><TableHead>Count / 数量</TableHead><TableHead>示例事件 / Sample events</TableHead></TableRow></TableHeader>
      <TableBody>
        {groups.map(g => <TableRow key={g.reason} data-testid={`exclusion-${g.reason}`}>
          <TableCell>{g.reason.replace(/_/g, " ")}</TableCell>
          <TableCell className="tabular-nums">{g.count}</TableCell>
          <TableCell className="text-xs muted truncate max-w-80">{g.measurement_event_ids.slice(0, 3).join(", ") || "—"}</TableCell>
        </TableRow>)}
      </TableBody>
    </Table>
  </div>;
}

export function AlignmentSamplesPanel({ batteryId, experimentId }: {
  batteryId: string; experimentId: string;
}) {
  const [filter, setFilter] = useState<"eligible" | "ambiguous" | "unmatched" | "all">("eligible");
  const [selected, setSelected] = useState<AlignmentSampleRow | null>(null);
  const samples = useQuery({
    queryKey: ["alignment-samples", batteryId, experimentId, filter],
    queryFn: () => client.getAlignmentSamples(batteryId, experimentId, filter, 12),
  });
  const rows = samples.data?.data.samples ?? [];
  return <div className="mt-6" data-testid="alignment-samples">
    <div className="flex flex-wrap gap-2 items-center">
      <h3>Inspect aligned sample / 查看对齐样本</h3>
      <div className="flex gap-1 ml-auto" role="group" aria-label="样本过滤">
        {(["eligible", "ambiguous", "unmatched", "all"] as const).map(f => <Button key={f} size="sm"
          variant={filter === f ? "secondary" : "ghost"} aria-pressed={filter === f}
          onClick={() => setFilter(f)}>{f}</Button>)}
      </div>
    </div>
    {samples.isLoading && <LoadingState />}
    {samples.error && <ErrorState error={samples.error} retry={() => void samples.refetch()} />}
    {rows.length > 0 && <Table>
      <TableHeader><TableRow>
        <TableHead>Event</TableHead><TableHead>Frame / 帧</TableHead><TableHead>Electrical / 电学</TableHead>
        <TableHead>Sync / 同步</TableHead><TableHead>SOC / 参考 SOC</TableHead><TableHead>Status</TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {rows.map(r => <TableRow key={r.measurement_event_id} data-testid={`align-row-${r.measurement_event_id}`}
          className="cursor-pointer" onClick={() => setSelected(r)}>
          <TableCell className="text-xs">{r.measurement_event_id.split("::").slice(-2).join("·")}</TableCell>
          <TableCell className="tabular-nums">{r.frame_index_raw ?? "—"}</TableCell>
          <TableCell className="text-xs">{r.electrical_asset_id ? `${r.electrical_asset_id} · ${r.electrical_record_locator}` : <span className="muted">null（不自动选择）</span>}</TableCell>
          <TableCell className="tabular-nums text-xs">{numberText(r.sync_error_s, 4)} s</TableCell>
          <TableCell className="tabular-nums">{numberText(r.targets["reference_soc_percent"], 1)}</TableCell>
          <TableCell>{r.analysis_eligible ? <Badge variant="secondary">Eligible / 可分析</Badge> : <Badge variant="outline">{r.match_status === "MATCHED_AMBIGUOUS" ? "Ambiguous / 歧义" : "Excluded / 排除"}</Badge>}</TableCell>
        </TableRow>)}
      </TableBody>
    </Table>}
    <p className="text-xs muted mt-2">点击行查看完整 provenance / Click a row for full provenance.</p>
    <Dialog open={!!selected} onOpenChange={open => { if (!open) setSelected(null); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Row provenance / 行级来源链</DialogTitle>
          <DialogDescription>Ultrasound Frame → MeasurementEvent → Electrical Record → Sync → Target</DialogDescription>
        </DialogHeader>
        {selected && <dl className="grid grid-cols-[170px_1fr] gap-x-4 gap-y-1.5 text-sm" data-testid="provenance-drawer">
          <dt className="muted">Ultrasound frame / 超声帧</dt><dd className="tabular-nums">{selected.frame_index_raw ?? "—"}</dd>
          <dt className="muted">Ultrasound timestamp</dt><dd className="text-xs">{selected.ultrasound_timestamp ?? "—"}</dd>
          <dt className="muted">MeasurementEvent</dt><dd className="text-xs"><code>{selected.measurement_event_id}</code></dd>
          <dt className="muted">Electrical asset / record</dt>
          <dd>{selected.electrical_asset_id
            ? <span className="text-xs">{selected.electrical_asset_id} · record {selected.electrical_record_locator} · {selected.electrical_timestamp}</span>
            : <span className="muted text-xs">null — ambiguous/unmatched，不自动选择电学记录 / never auto-selected</span>}</dd>
          <dt className="muted">Sync status / 同步</dt>
          <dd className="text-xs">{selected.match_status} · sync_error {numberText(selected.sync_error_s, 4)} s{selected.within_tolerance != null ? ` · within tolerance: ${selected.within_tolerance}` : ""}</dd>
          <dt className="muted">Analysis eligibility</dt><dd>{selected.analysis_eligible ? "Eligible / 可分析" : "Excluded / 排除"}</dd>
          <dt className="muted">Targets / 目标值</dt>
          <dd className="text-xs tabular-nums">{Object.entries(selected.targets).filter(([, v]) => v != null).map(([k, v]) => `${k}=${numberText(v, 2)}`).join(" · ") || "—"}</dd>
        </dl>}
      </DialogContent>
    </Dialog>
  </div>;
}
