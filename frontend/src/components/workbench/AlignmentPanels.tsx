import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { client, type AlignmentSampleRow } from "../../api/client";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../ui/dialog";
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from "../ui/table";
import { LoadingState, ErrorState } from "./shared";
import { numberText } from "../../lib/presentation";

export function AlignmentStatusBadge({ timebaseStatus = "PROVISIONAL", validatedSync = false }: {
  timebaseStatus?: string;
  validatedSync?: boolean;
}) {
  return <Badge variant="outline" data-testid="alignment-status-badge">
    {timebaseStatus} timebase · validated_sync={String(validatedSync)}</Badge>;
}

export function AlignmentSummary({ batteryId, experimentId, targetId }: {
  batteryId: string; experimentId: string; targetId: string | null;
}) {
  const summary = useQuery({
    queryKey: ["alignment-summary", batteryId, experimentId],
    queryFn: () => client.getAlignmentSummary(batteryId, experimentId),
  });
  const synchronization = useQuery({
    queryKey: ["synchronization", batteryId, experimentId],
    queryFn: () => client.getSynchronization(batteryId, experimentId),
  });
  const syncData = synchronization.data?.data;
  if (summary.isLoading) return <LoadingState />;
  if (summary.error) return <ErrorState error={summary.error} retry={() => void summary.refetch()} />;
  const d = summary.data!.data;
  const syncCountsMismatch = Boolean(syncData && (
    syncData.match_counts?.matched_unique !== d.matched_unique
    || syncData.match_counts?.matched_ambiguous !== d.ambiguous
    || (syncData.match_state === "MATCHED_UNIQUE" && (d.ambiguous > 0 || d.unmatched > 0))
  ));
  const stats = [
    { label: "Ultrasound frames / 超声帧", value: d.total_frames, testid: "align-total" },
    { label: "Matched unique / 唯一匹配", value: d.matched_unique, testid: "align-matched" },
    { label: "Ambiguous / 止义匹配", value: d.ambiguous, testid: "align-ambiguous" },
    { label: "Unmatched / 未匹配", value: d.unmatched, testid: "align-unmatched" },
    { label: "Target valid / 标签有效", value: d.target_valid?.[targetId ?? "reference_soc_percent"] ?? "—", testid: "align-target-valid" },
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
        {!d.target_labels_available && <p className="text-xs mb-2" role="status" data-testid="alignment-labels-pending">
          对齐检查已可用；SOC/SOH 等标签尚未生成，因此标签有效数为 0。完成后续标签步骤后可回来查看标签覆盖率。
          Alignment QA is available; target labels have not been generated yet.
        </p>}
        <h3 className="flex gap-2 items-center text-sm">Synchronization semantics / 同步语义 {<AlignmentStatusBadge
          timebaseStatus={syncData?.timebase_status ?? "UNKNOWN"}
          validatedSync={syncData?.validated_sync ?? false}
        />}</h3>
        <p className="text-xs muted mt-1">
          匹配唯一性与时间基准验证状态分开报告。PROVISIONAL 匹配仍不是完全验证同步；冲突、歧义与缺证据记录不会被自动选中。
          {syncData?.match_state ? ` 匹配状态：${syncCountsMismatch ? "INCONSISTENT" : syncData.match_state}。` : ""}
        </p>
        {syncCountsMismatch && <p className="text-xs text-destructive mt-1" role="alert" data-testid="alignment-counts-mismatch">
          帧级 MeasurementEvent 计数与同步摘要不一致；当前同步状态不可作为关联通过依据。请重新生成同步与事件产物，并确认 API 与产物版本一致。
        </p>}
        {synchronization.isError && <p className="text-xs text-destructive" role="alert">时间证据暂不可用；不能将当前行解释为已验证同步。</p>}
        {!synchronization.isLoading && !synchronization.isError && (syncData?.time_anchors ?? []).length === 0 &&
          <p className="text-xs text-destructive" role="alert">缺少逐资产时间锚点；绝对时间关联被阻断。</p>}
        {(syncData?.time_anchors ?? []).map((anchor) => <div
          key={anchor.asset_id}
          className={`mt-2 text-xs ${(anchor.conflicts ?? []).length || anchor.anchor_status === "UNVERIFIED" ? "text-destructive" : "muted"}`}
          data-testid={`alignment-anchor-${anchor.asset_id}`}
          role={(anchor.conflicts ?? []).length ? "alert" : undefined}
        >
          <strong>{anchor.asset_id}</strong> · {anchor.anchor_status} · {anchor.source_type ?? "无锚点来源"}
          {anchor.anchor_datetime ? ` · ${anchor.anchor_datetime}` : ""} · timezone {anchor.timezone_known ? "known" : "UNKNOWN"}
          {anchor.elapsed_min_s != null && anchor.elapsed_max_s != null
            ? ` · elapsed ${numberText(anchor.elapsed_min_s, 3)}–${numberText(anchor.elapsed_max_s, 3)} s`
            : ""}
          {(anchor.candidates ?? []).map((candidate, index) => <span key={`${candidate.anchor_id}-${index}`}>
            {` · candidate ${candidate.source_type ?? "unknown"}=${candidate.anchor_datetime ?? "missing"}`}
            {candidate.source_ref ? ` (${candidate.source_ref})` : ""}
          </span>)}
          {(anchor.evidence ?? []).map((item, index) => <span key={`${item.source_type}-${index}`}>
            {` · evidence ${item.source_type ?? "unknown"}: ${item.source_ref ?? "source unavailable"}`}
            {item.raw_value != null ? ` raw=${String(item.raw_value)}` : ""}
            {item.parsed_value ? ` parsed=${item.parsed_value}` : ""}
            {item.source_sha256 ? ` sha256:${item.source_sha256.slice(0, 12)}` : ""}
          </span>)}
          {(anchor.conflicts ?? []).map((item, index) => <span key={`${item.source_type}-${index}`}>
            {` · CONFLICT ${item.source_type ?? "unknown"}: ${item.source_ref ?? item.message ?? "evidence conflict"}`}
            {item.raw_value != null ? ` raw=${String(item.raw_value)}` : ""}
            {item.parsed_value ? ` parsed=${item.parsed_value}` : ""}
            {item.message ? ` (${item.message})` : ""}
          </span>)}
        </div>)}
        {(syncData?.time_anchor_warnings ?? []).map((warning, index) => <p
          key={`${warning}-${index}`} className="mt-1 text-xs text-destructive" role="alert">{warning}</p>)}
        {(syncData?.time_anchor_limitations ?? []).length ? <p className="mt-1 text-xs muted">
          时间基准限制：{syncData?.time_anchor_limitations.join("；")}
        </p> : null}
        {(syncData?.electrical_assets ?? []).length > 0 && <div className="mt-3" data-testid="electrical-time-coverage">
          <p className="text-xs font-medium">电学 DataAsset 时间覆盖（由真实 record timestamps 汇总）</p>
          {(syncData?.electrical_assets ?? []).map((asset) => <p
            key={asset.electrical_asset_id}
            className="mt-1 text-xs muted break-all"
            data-testid={`electrical-asset-clock-${asset.electrical_asset_id}`}
          >
            <strong>{asset.electrical_asset_id}</strong> · {asset.record_count.toLocaleString()} records ·
            {` ${asset.timestamp_min} → ${asset.timestamp_max}`} · {asset.timestamp_representation}
            {asset.timezone_name ? ` (${asset.timezone_name})` : " · timezone UNKNOWN"}
            {` · source rows ${asset.source_row_min ?? "?"}–${asset.source_row_max ?? "?"}`}
            {(asset.source_files ?? []).length ? ` · ${(asset.source_files ?? []).join("; ")}` : " · source file unavailable"}
          </p>)}
          {(syncData?.electrical_coverage_overlaps ?? []).map((overlap) => <p
            key={overlap.asset_ids.join("-")}
            className="mt-1 text-xs muted"
            data-testid={`electrical-coverage-overlap-${overlap.asset_ids.join("-")}`}
            role="status"
          >
            电学 asset 覆盖区间重叠：{overlap.asset_ids.join(" ↔ ")}，{numberText(overlap.overlap_seconds, 1)} s
            {overlap.basis === "NAIVE_WALL_CLOCK" ? "（仅按无时区 wall-clock 比较）" : "（offset-aware instant）"}；需结合帧级候选判断是否产生匹配歧义。
          </p>)}
          {(syncData?.electrical_incompatible_clock_pairs ?? []).map((assets) => <p
            key={assets.join("-")}
            className="mt-1 text-xs text-destructive"
            role="alert"
          >无法比较电学 asset 时间覆盖：{assets.join(" ↔ ")} 的 naive/offset-aware 表示不一致。
          </p>)}
        </div>}
        {(syncData?.electrical_mixed_clock_assets ?? []).map((assetId) => <p
          key={assetId}
          className="mt-2 text-xs text-destructive"
          data-testid={`electrical-mixed-clock-${assetId}`}
          role="alert"
        >{assetId} 的记录混合 naive 与 offset-aware timestamps；其时间顺序不可安全比较，相关声学帧已阻断匹配。</p>)}
        <p className="text-xs muted mt-1">
          Sync error / 同步误差: max |error| = <span className="tabular-nums">{numberText(d.sync_quality?.max_sync_error_s ?? null, 4)} s</span>
          {d.sync_quality?.max_sync_error_limit_s != null && <> · 允许上限 {numberText(d.sync_quality.max_sync_error_limit_s, 2)} s</>}
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
          <dt className="muted">Ultrasound source / 原始 TXT 行</dt>
          <dd className="text-xs break-all">
            {selected.ultrasound_asset_id ?? "—"} · {selected.ultrasound_source_file ?? "source path unavailable"}
            {selected.ultrasound_source_line_index != null ? ` · line ${selected.ultrasound_source_line_index}` : ""}
            <br /><code>SHA-256 {selected.ultrasound_source_sha256 ?? "unavailable — parser manifest missing"}</code>
          </dd>
          <dt className="muted">Ultrasound timestamp</dt><dd className="text-xs">{selected.ultrasound_timestamp ?? "—"}</dd>
          <dt className="muted">MeasurementEvent</dt><dd className="text-xs"><code>{selected.measurement_event_id}</code></dd>
          <dt className="muted">Electrical asset / record</dt>
          <dd>{selected.electrical_asset_id
            ? <span className="text-xs break-all">{selected.electrical_asset_id} · {selected.electrical_source_file ?? "source path unavailable"} · record {selected.electrical_record_locator} · {selected.electrical_timestamp}<br /><code>SHA-256 {selected.electrical_source_sha256 ?? "unavailable — parser manifest missing"}</code></span>
            : <span className="muted text-xs">null — ambiguous/unmatched，不自动选择电学记录 / never auto-selected</span>}</dd>
          <dt className="muted">Sync status / 同步</dt>
          <dd className="text-xs">{selected.match_status} · nearest |Δt| {numberText(selected.sync_error_s, 4)} s
            {selected.signed_time_delta_s != null ? ` · nearest candidate Δt (electrical − ultrasound) ${numberText(selected.signed_time_delta_s, 4)} s` : " · direction unavailable (multiple tied timestamp groups or missing timestamp)"}
            {selected.within_tolerance != null ? ` · within tolerance: ${selected.within_tolerance}` : ""}</dd>
          {(selected.match_status === "MATCHED_AMBIGUOUS" || selected.match_status === "OUT_OF_TOLERANCE") && <>
            <dt className="muted">{selected.match_status === "OUT_OF_TOLERANCE"
              ? "Nearest electrical candidate rejected by tolerance / 超容差候选"
              : "Unresolved electrical candidates / 未消歧候选"}</dt>
            <dd className="space-y-2" data-testid="alignment-candidates">
              <p className="text-xs">{selected.ambiguity_type ?? selected.match_status} · {selected.candidate_record_count ?? selected.electrical_candidates?.length ?? 0} records across {selected.candidate_timestamp_count ?? "?"} timestamp groups. No candidate was selected.
                {selected.match_status === "OUT_OF_TOLERANCE" ? " Nearest candidate exceeds configured synchronization tolerance." : ""}
              </p>
              {selected.candidate_details_available === false && <p className="text-xs text-destructive" role="alert">
                Candidate details are unavailable for this artifact version; regenerate MeasurementEvents from current synchronization outputs before adjudicating.
              </p>}
              {(selected.electrical_candidates ?? []).map((candidate, index) => <div
                key={`${candidate.electrical_asset_id}-${candidate.electrical_record_locator}-${index}`}
                className="border rounded-md p-2 text-xs break-all"
                data-testid={`alignment-candidate-${index}`}
              >
                <strong>{candidate.electrical_asset_id ?? "asset unavailable"}</strong>
                {` · record ${candidate.electrical_record_locator ?? "?"} · ${candidate.electrical_timestamp ?? "timestamp unavailable"}`}
                {` · |Δt| ${numberText(candidate.sync_error_s, 4)} s`}
                {candidate.signed_time_delta_s != null ? ` · signed Δt ${numberText(candidate.signed_time_delta_s, 4)} s` : ""}
                {` · duplicate group size ${candidate.electrical_timestamp_duplicate_count}`}
                {candidate.boundary_flag ? " · step/cycle boundary" : ""}
                <br />{candidate.electrical_source_file ?? "source path unavailable"}
                <br /><code>SHA-256 {candidate.electrical_source_sha256 ?? "unavailable"}</code>
              </div>)}
            </dd>
          </>}
          <dt className="muted">Analysis eligibility</dt><dd>{selected.analysis_eligible ? "Eligible / 可分析" : "Excluded / 排除"}</dd>
          <dt className="muted">Targets / 目标值</dt>
          <dd className="text-xs tabular-nums">{Object.entries(selected.targets).filter(([, v]) => v != null).map(([k, v]) => `${k}=${numberText(v, 2)}`).join(" · ") || "—"}</dd>
        </dl>}
      </DialogContent>
    </Dialog>
  </div>;
}
