import { useQuery } from "@tanstack/react-query";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";
import { client } from "../../api/client";
import { Button } from "../ui/button";

const Plot = createPlotlyComponent(Plotly);
const layout = {
  autosize: true, height: 170, margin: { l: 44, r: 42, t: 8, b: 35 },
  paper_bgcolor: "#ffffff", plot_bgcolor: "#ffffff", showlegend: false,
  font: { family: "Inter, sans-serif", size: 10, color: "#606d73" },
  xaxis: { gridcolor: "#edf0f0", zeroline: false },
  yaxis: { gridcolor: "#edf0f0", zeroline: false },
};
const config = { responsive: true, displayModeBar: false, displaylogo: false };

export function ElectricalMiniView({ batteryId, experimentId }: { batteryId: string; experimentId: string }) {
  const events = useQuery({ queryKey: ["overview-events", batteryId, experimentId], queryFn: () => client.getMeasurementEvents(batteryId, experimentId, 100) });
  if (events.isPending) return <p className="signal-placeholder" role="status">加载电学预览…</p>;
  if (events.isError) return <div className="signal-placeholder">电学预览暂不可用<Button variant="ghost" onClick={() => void events.refetch()}>重试电学预览</Button></div>;
  const rows = events.data?.data.events ?? [];
  if (!rows.some(r => r.voltage_v != null || r.current_a != null)) return <p className="signal-placeholder">暂无电学预览。</p>;
  const hasTime = rows.every(r => !!r.timestamp);
  const x = rows.map((r, i) => hasTime ? r.timestamp : i + 1);
  return <figure aria-label="电压与电流局部预览"><Plot data={[
    { x, y: rows.map(r => r.voltage_v), type: "scatter", mode: "lines", name: "电压 V", line: { color: "#334155", width: 1.5 }, connectgaps: false },
    { x, y: rows.map(r => r.current_a), type: "scatter", mode: "lines", name: "电流 A", yaxis: "y2", line: { color: "#0d9488", width: 1.5 }, connectgaps: false },
  ]} layout={{ ...layout, xaxis: { ...layout.xaxis, type: hasTime ? "date" : "linear", title: { text: hasTime ? "Timestamp" : "预览事件顺序（非时间轴）" } }, yaxis: { ...layout.yaxis, title: { text: "V" } }, yaxis2: { overlaying: "y", side: "right", title: { text: "A" }, showgrid: false } }} config={config} style={{ width: "100%", height: 170 }} useResizeHandler/>
    <figcaption className="text-xs muted">深灰：电压 · 青绿：电流。前 {rows.length} 个事件，非完整循环。{!hasTime && "API 未提供完整时间戳，按返回顺序展示。"}</figcaption></figure>;
}

export function UltrasoundMiniView({ batteryId, experimentId }: { batteryId: string; experimentId: string }) {
  const frames = useQuery({ queryKey: ["overview-frames", batteryId, experimentId], queryFn: () => client.listWaveformFrames(batteryId, experimentId) });
  const rows = frames.data?.data.frames ?? [];
  const first = rows[0];
  const unique = first && rows.filter(r => r.frame_index === first.frame_index).length === 1;
  const waveform = useQuery({ queryKey: ["overview-waveform", batteryId, experimentId, first?.frame_index], queryFn: () => client.getWaveformFrame(batteryId, experimentId, first!.frame_index, 500), enabled: !!unique });
  const gates = useQuery({ queryKey: ["gates", batteryId, experimentId], queryFn: () => client.listGates(batteryId, experimentId) });
  if (frames.isPending || (unique && waveform.isPending)) return <p className="signal-placeholder" role="status">加载 A-scan…</p>;
  if (frames.isError || waveform.isError) return <div className="signal-placeholder">波形预览暂不可用<Button variant="ghost" onClick={() => { void frames.refetch(); if (unique) void waveform.refetch(); }}>重试波形预览</Button></div>;
  if (!unique) return <p className="signal-placeholder">{first ? "帧编号跨资产重复，无法唯一定位预览。" : "暂无波形。"}</p>;
  const samples = waveform.data?.data.samples ?? [];
  return <figure aria-label="超声 A-scan 与已有闸门预览"><Plot data={[{ x: samples.map(s => s.sample_index), y: samples.map(s => s.amplitude_a_u), type: "scatter", mode: "lines", name: "A-scan", line: { color: "#334155", width: 1 } }]}
    layout={{ ...layout, xaxis: { ...layout.xaxis, title: { text: "Sample index" } }, yaxis: { ...layout.yaxis, title: { text: "a.u." } }, shapes: (gates.data?.data.gates ?? []).filter(g => g.start_sample != null && g.end_sample != null && g.waveform_length === waveform.data?.data.waveform_length).map(g => ({ type: "rect", xref: "x", yref: "paper", x0: g.start_sample!, x1: g.end_sample!, y0: 0, y1: 1, fillcolor: "rgba(217,119,6,.10)", line: { color: "#b45309", width: 1 } })) }} config={config} style={{ width: "100%", height: 170 }} useResizeHandler/>
    <figcaption className="text-xs muted">首个可定位帧 · API 降采样预览；非代表帧或 QA 结论。{gates.isError ? "闸门加载失败。" : "仅叠加已保存的同长度闸门。"}</figcaption></figure>;
}
