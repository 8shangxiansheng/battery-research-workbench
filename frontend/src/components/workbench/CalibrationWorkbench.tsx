import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Ruler } from "lucide-react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";
import { client, type GateCalibrationResponse, type GateTemplateEntry } from "../../api/client";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Checkbox } from "../ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../ui/dialog";
import { LoadingState, ErrorState } from "./shared";
import { numberText } from "../../lib/presentation";

const Plot = createPlotlyComponent(Plotly);

const GATE_COLORS: Record<string, string> = {
  SWA_SURFACE_GATE: "#2f7d6d",
  BOTTOM_AMPLITUDE_GATE: "#426976",
  TOF_SURFACE_REFERENCE_GATE: "#a26f2f",
  TOF_BOTTOM_GATE: "#7d4d2f",
  ATTENUATION_BOTTOM_GATE: "#5b5470",
  BPS_BOTTOM_GATE: "#7a5470",
};

function OverlayPlot({ frameData, templates, gates, onResize }: {
  frameData: GateCalibrationResponse["frames"][number] | undefined;
  templates: GateTemplateEntry[];
  gates: Record<string, { start: number; end: number }>;
  onResize: (gateId: string, start: number, end: number) => void;
}) {
  const shapes = templates.map(t => {
    const adj = gates[t.gate_template_id];
    const start = adj?.start ?? t.python_start;
    const end = adj?.end ?? t.python_end_exclusive;
    return {
      type: "rect" as const, xref: "x" as const, yref: "paper" as const,
      x0: start, x1: end, y0: 0, y1: 1,
      fillcolor: `${GATE_COLORS[t.gate_template_id] ?? "#426976"}18`,
      line: { color: GATE_COLORS[t.gate_template_id] ?? "#426976", width: 1.4 },
      editable: true,
    };
  });
  return <div className="plot-wrap" data-testid="calibration-overlay" aria-label="标定帧波形与包络叠加图">
    {frameData ? <Plot
      data={[
        { x: frameData.samples.map(s => s.sample_index), y: frameData.samples.map(s => s.amplitude_a_u), type: "scatter", mode: "lines", line: { color: "#426976", width: 1.2 }, name: "Waveform / 波形", hovertemplate: "Sample %{x}<br>%{y:.3f}<extra></extra>" },
        { x: frameData.samples.map(s => s.sample_index), y: frameData.samples.map(s => s.envelope_a_u), type: "scatter", mode: "lines", line: { color: "#2f7d6d", width: 1.4, dash: "dot" }, name: "Envelope / 包络", hovertemplate: "Sample %{x}<br>env %{y:.3f}<extra></extra>" },
      ]}
      layout={{
        autosize: true, height: 400, margin: { l: 64, r: 24, t: 28, b: 52 },
        paper_bgcolor: "#fff", plot_bgcolor: "#fff", font: { family: "Inter, sans-serif", size: 12, color: "#59666d" },
        showlegend: true, legend: { orientation: "h", y: -0.18 },
        dragmode: "zoom" as const,
        xaxis: { title: { text: "Sample index / 采样点" }, gridcolor: "#edf0f0", zeroline: false },
        yaxis: { title: { text: "Amplitude (a.u.)" }, gridcolor: "#edf0f0" },
        shapes,
      }}
      config={{ responsive: true, displayModeBar: false, scrollZoom: true, displaylogo: false }}
      style={{ width: "100%", height: 400 }} useResizeHandler
      onRelayout={relayout => {
        // Plotly editable shapes report x0/x1 shifts on drag/resize
        for (const t of templates) {
          const x0 = relayout[`shapes[${templates.indexOf(t)}].x0`];
          const x1 = relayout[`shapes[${templates.indexOf(t)}].x1`];
          if (typeof x0 === "number" && typeof x1 === "number") onResize(t.gate_template_id, Math.round(x0), Math.round(x1));
        }
      }}
    /> : <LoadingState />}
  </div>;
}

/** Calibrate Gates / 标定闸门 — deterministic backend-selected representative
 *  frames (never target-informed), waveform+envelope overlay, drag/resize
 *  gate shapes, peak containment diagnostics, confirm/freeze. */
export function CalibrationWorkbench({ batteryId, experimentId, waveformLength }: {
  batteryId: string; experimentId: string; waveformLength: number | undefined;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [framePos, setFramePos] = useState(0);
  const [showEnvelope, setShowEnvelope] = useState(true);
  const [gates, setGates] = useState<Record<string, { start: number; end: number }>>({});
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [frozen, setFrozen] = useState<{ id: string; reuse: string } | null>(null);

  const calib = useQuery({
    queryKey: ["gate-calibration", batteryId, experimentId],
    queryFn: () => client.getGateCalibration(batteryId, experimentId, 32),
    enabled: open,
  });
  const freeze = useMutation({
    mutationFn: () => client.freezeGateCalibration(batteryId, experimentId, {
      confirmed_by: "user", calibration_basis: "PREDECLARED_PROTOCOL_GATE",
    }),
    onSuccess: r => {
      setConfirmOpen(false);
      setFrozen({ id: r.data.gate_calibration_id, reuse: r.data.reuse_status });
      void qc.invalidateQueries({ queryKey: ["gate-calibration", batteryId, experimentId] });
    },
  });

  const data = calib.data?.data;
  const frameData = useMemo(() => data?.frames[framePos], [data, framePos]);
  const frameDiag = useMemo(() => {
    if (!data || !frameData) return null;
    return data.diagnostics.find(d => d.frame_index === frameData.frame_index) ?? null;
  }, [data, frameData]);
  const edgeHits = useMemo(() => (data?.diagnostics ?? []).filter(d => d.edge_hit).length, [data]);

  function resize(gateId: string, start: number, end: number) {
    const max = (waveformLength ?? 1250) - 1;
    setGates(prev => ({ ...prev, [gateId]: { start: Math.max(0, start), end: Math.min(max, end) } }));
  }

  return <section className="panel mt-6 !p-5" data-testid="calibrate-gates">
    <div className="flex flex-wrap gap-3 items-center justify-between">
      <div>
        <h2 className="flex gap-2 items-center"><Ruler size={18} />Calibrate Gates / 标定闸门</h2>
        <p className="muted text-sm mt-1">后端确定性地挑选代表性帧（不使用 SOC 相关性或模型分数），复核后冻结闸门。</p>
      </div>
      <Button onClick={() => setOpen(o => !o)} aria-expanded={open} data-testid="calibrate-toggle">{open ? "收起 / Close" : "开始标定 / Calibrate"}</Button>
    </div>
    {frozen && <p className="notice mt-3" role="status" data-testid="calibration-frozen">
      <CheckCircle2 size={15} className="inline mr-1" />闸门已冻结 / Gates frozen · {frozen.id} · {frozen.reuse === "REUSED" ? "复用已有记录" : "新记录"}</p>}
    {open && <>
      {calib.isLoading && <LoadingState />}
      {calib.error && <ErrorState error={calib.error} retry={() => void calib.refetch()} />}
      {data && <>
        <div className="flex flex-wrap gap-3 items-center mt-4 text-sm">
          <span>Calibration frames / 标定波形: <strong data-testid="calibration-frame-count">{data.calibration_frame_ids.length}</strong></span>
          <label className="flex gap-1 items-center"><Checkbox checked={showEnvelope} onCheckedChange={v => setShowEnvelope(!!v)} />Show envelope / 显示包络</label>
          <span className="muted text-xs">选择依据: {String(calib.data?.meta?.selection_basis ?? "PREDECLARED_PROTOCOL_GATE")}</span>
        </div>
        <div className="flex gap-2 items-center mt-3">
          <Button variant="outline" size="sm" disabled={framePos === 0} onClick={() => setFramePos(p => p - 1)} aria-label="上一标定帧">←</Button>
          <span className="text-sm">Frame {data.frames[framePos]?.frame_index}（{framePos + 1}/{data.frames.length}）</span>
          <Button variant="outline" size="sm" disabled={framePos >= data.frames.length - 1} onClick={() => setFramePos(p => p + 1)} aria-label="下一标定帧">→</Button>
          {frameDiag && <Badge variant={frameDiag.edge_hit ? "outline" : "secondary"} className="ml-2">
            Peak containment {numberText(frameDiag.peak_containment_fraction * 100, 1)}%{frameDiag.edge_hit ? " · Edge hit!" : ""}</Badge>}
          {edgeHits > 0 && <span className="text-xs muted">{edgeHits} 帧 packet 触及闸门边缘 / edge hits</span>}
        </div>
        <div className="mt-3"><OverlayPlot frameData={frameData} templates={showEnvelope ? data.gate_templates : data.gate_templates} gates={gates} onResize={resize} /></div>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          {data.gate_templates.map(t => {
            const adj = gates[t.gate_template_id];
            return <Badge key={t.gate_template_id} variant="outline" data-testid={`gate-chip-${t.gate_template_id}`}>
              {t.role_zh} / {t.role_en}: {adj ? `${adj.start}–${adj.end}` : `${t.python_start}–${t.python_end_exclusive}`}
              {adj && <span className="ml-1 muted">(已调整)</span>}
            </Badge>;
          })}
        </div>
        <details className="mt-3"><summary className="text-sm">高级信息 / Advanced</summary>
          <p className="text-xs muted mt-2">Source template: MATLAB 1-based inclusive → Python 0-based half-open · 标定帧 IDs: {data.calibration_frame_ids.slice(0, 8).join(", ")}…</p>
          <p className="text-xs muted">配置（probe/battery）变更后需要重新标定；冻结记录包含完整 provenance。</p>
        </details>
        <div className="mt-4"><Button onClick={() => setConfirmOpen(true)} data-testid="confirm-gates">Confirm Gates / 确认闸门</Button></div>
        <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}><DialogContent>
          <DialogHeader><DialogTitle>确认并冻结闸门 / Confirm and freeze gates</DialogTitle>
            <DialogDescription>冻结后生成 GateCalibrationRecord（含标定帧、模板、来源），下游特征引用冻结 gate。此操作幂等：相同配置复用同一记录。</DialogDescription></DialogHeader>
          <p className="text-sm">标定帧 {data.calibration_frame_ids.length} 个 · 选择依据 PREDECLARED_PROTOCOL_GATE（目标盲选）。</p>
          {freeze.error && <p role="alert" className="text-sm">冻结失败，请重试。</p>}
          <DialogFooter><Button variant="outline" onClick={() => setConfirmOpen(false)}>取消</Button>
            <Button disabled={freeze.isPending} onClick={() => freeze.mutate()} data-testid="freeze-confirm">{freeze.isPending ? "冻结中…" : "确认冻结 / Freeze"}</Button></DialogFooter>
        </DialogContent></Dialog>
      </>}
    </>}
  </section>;
}
