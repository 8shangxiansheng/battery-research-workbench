import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { client, type FeatureLabelPreviewRow, type FeatureLabelPreviewResponse } from "../../api/client";
import { Button } from "../ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../ui/dialog";
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from "../ui/table";
import { LoadingState, ErrorState } from "./shared";
import { numberText } from "../../lib/presentation";

const FEATURE_LABELS: Record<string, string> = {
  SWA: "SWA / 表面波幅值", BOTTOM_AMP: "Bottom-wave Amplitude / 底波幅值",
  TOF_XCORR: "XCorr TOF / 互相关TOF", ATTEN_MAX: "Attenuation max / 衰减最大",
  ATTEN_MEAN: "Attenuation mean / 衰减平均", ATTEN_ENERGY: "Attenuation energy / 衰减能量",
  BPS: "BPS / 底波相移",
};
export const TARGET_LABELS: Record<string, string> = {
  reference_soc_percent: "Reference SOC / 参考 SOC",
  temperature_c: "Temperature / 温度",
  soh_capacity_reference_percent: "SOH / 健康状态",
  voltage_v: "Voltage / 电压",
  current_a: "Current / 电流",
};
const STATE_ZH: Record<string, string> = { charge: "充电 / Charge", discharge: "放电 / Discharge", rest: "静置 / Rest" };

export function EligibilityBreakdown({ summary }: { summary: FeatureLabelPreviewResponse["summary"] }) {
  const funnel = [
    { label: "Raw ultrasound frames / 原始超声帧", value: summary.total_frames, testid: "funnel-raw" },
    { label: "Aligned events / 已对齐事件", value: summary.aligned_events, testid: "funnel-aligned" },
    { label: "Target-valid rows / 目标有效行", value: summary.aligned_events - (summary.excluded_by_reason["TARGET_MISSING"] ?? 0) - (summary.excluded_by_reason["AMBIGUOUS_SYNC"] ?? 0), testid: "funnel-target-valid" },
    { label: "Feature-complete rows / 特征完整行", value: summary.aligned_events - (summary.excluded_by_reason["FEATURE_MISSING"] ?? 0), testid: "funnel-feature-complete" },
    { label: "Final eligible rows / 最终可分析行", value: summary.eligible_rows, testid: "funnel-eligible" },
  ];
  return <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mt-4" data-testid="eligibility-breakdown">
    {funnel.map(f => <div key={f.label} className="feature-card !p-3">
      <p className="text-xs muted leading-snug">{f.label}</p>
      <p className="text-lg tabular-nums mt-1" data-testid={f.testid}>{numberText(f.value, 0)}</p>
    </div>)}
  </div>;
}

export function FeatureLabelRowDrawer({ row, targetId, features, onClose }: {
  row: FeatureLabelPreviewRow | null; targetId: string; features: string[]; onClose: () => void;
}) {
  return <Dialog open={!!row} onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Row provenance / 行级来源链</DialogTitle>
        <DialogDescription>waveform → gate → feature → MeasurementEvent → electrical record → target</DialogDescription>
      </DialogHeader>
      {row && <dl className="grid grid-cols-[180px_1fr] gap-x-4 gap-y-1.5 text-sm" data-testid="feature-label-row-provenance">
        <dt className="muted">Ultrasound frame / 超声帧</dt><dd className="tabular-nums">{row.frame_index_raw ?? "—"}</dd>
        <dt className="muted">Gate / 闸门</dt><dd className="text-xs">{features.includes("SWA") && "SWA_SURFACE_GATE "}{features.includes("BOTTOM_AMP") && "BOTTOM_AMPLITUDE_GATE "}{features.includes("TOF_XCORR") && "TOF_SURFACE_REFERENCE_GATE + TOF_BOTTOM_GATE "}{features.includes("BPS") && "BPS_BOTTOM_GATE "}{features.includes("ATTEN_MAX") && "ATTENUATION_BOTTOM_GATE"}</dd>
        <dt className="muted">Feature definitions</dt><dd className="text-xs">{features.map(f => FEATURE_LABELS[f] ?? f).join(" · ")}</dd>
        <dt className="muted">MeasurementEvent</dt><dd className="text-xs"><code>{row.measurement_event_id}</code></dd>
        <dt className="muted">Electrical record / 电学记录</dt><dd className="text-xs">{row.electrical_asset_id ?? "null（ambiguous — 未选择）"}</dd>
        <dt className="muted">Sync error / 同步误差</dt><dd className="tabular-nums text-xs">{numberText(row.sync_error_s, 4)} s（provisional timebase）</dd>
        <dt className="muted">Target / 目标值</dt><dd>{TARGET_LABELS[targetId] ?? targetId} = <span className="tabular-nums">{numberText(row.target, 3)}</span></dd>
      </dl>}
    </DialogContent>
  </Dialog>;
}

export function FeatureLabelTablePreview({ batteryId, experimentId, targetId, features }: {
  batteryId: string; experimentId: string; targetId: string; features: string[];
}) {
  const [openRow, setOpenRow] = useState<FeatureLabelPreviewRow | null>(null);
  const preview = useMutation({
    mutationFn: () => client.postFeatureLabelPreview(batteryId, experimentId, { target_id: targetId, features }),
  });
  function run() { preview.mutate(); }
  return <div data-testid="feature-label-table">
    <div className="flex gap-3 items-center">
      <Button onClick={run} data-testid="preview-table-btn" disabled={!features.length}>
        Preview Feature–Label Table / 预览特征-标签表</Button>
      {features.length === 0 && <span className="text-xs muted">先在 Features 步骤选择特征。</span>}
    </div>
    {preview.isPending && <LoadingState />}
    {preview.error && <ErrorState error={preview.error} retry={() => preview.mutate()} />}
    {preview.data && (() => {
      const d = preview.data.data;
      return <>
        <div className="grid md:grid-cols-4 gap-3 mt-4" data-testid="feature-label-summary">
          {[
            { label: "Target / 目标", value: TARGET_LABELS[d.target_id] ?? d.target_id },
            { label: "Target source / 目标来源", value: d.target_source ?? "—" },
            { label: "Feature count / 特征数", value: String(d.features.length) },
            { label: "Eligible / Excluded rows", value: `${numberText(d.summary.eligible_rows, 0)} / ${numberText(d.summary.excluded_rows, 0)}` },
            { label: "Cycles / 循环", value: d.summary.cycles.join(", ") || "—" },
            { label: "Missing values / 缺失", value: String(d.summary.missing_values) },
            { label: "Alignment / 对齐", value: d.summary.alignment_status.replace(/_/g, " ").toLowerCase() },
            { label: "Readiness / 就绪", value: d.target_readiness ?? "—" },
          ].map(x => <div key={x.label} className="feature-card !p-3">
            <p className="text-xs muted">{x.label}</p>
            <p className="text-sm mt-1">{x.value}</p>
          </div>)}
        </div>
        <EligibilityBreakdown summary={d.summary} />
        <div className="mt-4 overflow-x-auto">
          <Table>
            <TableHeader><TableRow>
              <TableHead>Event</TableHead>
              {d.features.map(f => <TableHead key={f}>{FEATURE_LABELS[f] ?? f}</TableHead>)}
              <TableHead>{TARGET_LABELS[d.target_id] ?? d.target_id}</TableHead>
              <TableHead>State / 状态</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {d.rows.map(r => <TableRow key={r.measurement_event_id} data-testid={`fl-row-${r.measurement_event_id}`}
                className="cursor-pointer" onClick={() => setOpenRow(r)}>
                <TableCell className="text-xs">{r.frame_index_raw}</TableCell>
                {d.features.map(f => <TableCell key={f} className="tabular-nums">{numberText(r.values[f], 2)}</TableCell>)}
                <TableCell className="tabular-nums font-medium">{numberText(r.target, 2)}</TableCell>
                <TableCell className="text-xs">{STATE_ZH[r.state] ?? r.state}</TableCell>
              </TableRow>)}
            </TableBody>
          </Table>
          <p className="text-xs muted mt-2">{d.rows.length} / {numberText(d.summary.eligible_rows, 0)} eligible rows shown · 一行 = 一个 eligible MeasurementEvent · 点击行查看 provenance。</p>
        </div>
        <FeatureLabelRowDrawer row={openRow} targetId={d.target_id} features={d.features} onClose={() => setOpenRow(null)} />
      </>;
    })()}
  </div>;
}
