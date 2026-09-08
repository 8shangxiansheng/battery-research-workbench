import { useQuery } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { client, type PhysicalFeatureBlock } from "../../api/client";
import { Badge } from "../ui/badge";
import { LoadingState, ErrorState } from "./shared";
import { numberText } from "../../lib/presentation";

/** Physical feature cards for the current frame — values computed by the
 *  backend deterministic modules; the frontend never recomputes them. */
export function PhysicalFeatureCards({ batteryId, experimentId, frameIndex }: {
  batteryId: string; experimentId: string; frameIndex: number | undefined;
}) {
  const phys = useQuery({
    queryKey: ["physical-features", batteryId, experimentId],
    queryFn: () => client.listPhysicalFeatures(batteryId, experimentId, 200),
  });
  if (phys.isLoading) return <LoadingState />;
  if (phys.error) return <ErrorState error={phys.error} retry={() => void phys.refetch()} />;
  const blocks = phys.data?.data.features ?? [];
  const valueAt = (b: PhysicalFeatureBlock) => (frameIndex != null ? b.values[frameIndex] ?? null : null);
  return <div className="grid md:grid-cols-5 gap-3 mt-4" data-testid="physical-features" aria-label="物理特征（当前帧）">
    {blocks.map(b => {
      const v = valueAt(b);
      const blocked = v == null;
      return <div key={b.feature_code} className="feature-card !p-4" data-testid={`phys-${b.feature_code}`}>
        <h3 className="text-sm font-medium leading-snug">{b.display_name_en}</h3>
        <p className="text-xs muted mt-0.5">{b.display_name_zh}</p>
        <p className="mt-3 text-lg tabular-nums">{blocked ? "—" : numberText(v, 3)}<span className="text-xs muted ml-1">{b.unit}</span></p>
        {b.physical_time_blocked && <p className="text-xs muted mt-2"><TriangleAlert size={12} className="inline mr-1" />物理时间需已验证采样率</p>}
        {b.blocked_features?.map(bf => <Badge key={bf.code} variant="outline" className="mt-2">{bf.code}: {bf.status}</Badge>)}
        <p className="text-[10px] muted mt-2 truncate" title={b.method}>{b.gate_template_id}</p>
      </div>;
    })}
  </div>;
}

/** Electrical state of the frame's single MeasurementEvent. All gate-local
 *  features of the same frame inherit THIS context — no per-gate rematch. */
export function ElectricalStatePanel({ event }: {
  event: {
    measurement_event_id: string;
    voltage_v: number | null; current_a: number | null; soc_reference_percent: number | null;
    step_type?: string | null; temperature_c?: number | null;
    cycle_index_raw: number | null; step_index_raw: number | null;
  } | undefined;
}) {
  if (!event) {
    return <div className="feature-card mt-4 !p-4" data-testid="electrical-state">
      <h3 className="text-sm font-medium">Electrical State / 电学状态</h3>
      <p className="text-xs muted mt-2">当前帧没有唯一匹配的电学事件。/ No unique electrical event for this frame.</p>
    </div>;
  }
  const rows = [
    { label: "Voltage / 电压", value: event.voltage_v != null ? `${numberText(event.voltage_v, 4)} V` : null },
    { label: "Current / 电流", value: event.current_a != null ? `${numberText(event.current_a, 4)} A` : null },
    { label: "Reference SOC / 参考 SOC", value: event.soc_reference_percent != null ? `${numberText(event.soc_reference_percent, 2)} %` : null },
    { label: "Temperature / 温度", value: event.temperature_c != null ? `${numberText(event.temperature_c, 2)} °C` : null },
    { label: "SOH / 健康状态", value: null, note: "由特征关系页的 cycle 级摘要提供" },
    { label: "Cycle / 循环", value: event.cycle_index_raw != null ? String(event.cycle_index_raw) : null },
    { label: "Step / 工步", value: event.step_index_raw != null ? String(event.step_index_raw) : null },
    { label: "State / 状态", value: event.step_type ?? null },
  ];
  return <div className="feature-card mt-4 !p-4" data-testid="electrical-state" aria-label="当前帧电学状态">
    <h3 className="text-sm font-medium">Electrical State / 电学状态 <Badge variant="secondary" className="ml-2">同一 MeasurementEvent</Badge></h3>
    <dl className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-2 mt-3 text-sm">
      {rows.map(r => <div key={r.label}>
        <dt className="text-xs muted">{r.label}</dt>
        <dd className="tabular-nums">{r.value ?? (r.note ? <span className="text-xs muted">{r.note}</span> : "—")}</dd>
      </div>)}
    </dl>
    <p className="text-[10px] muted mt-3">闸门位置从不用于重新匹配电学数据 — 同一帧的所有闸门特征共享本状态。Gate sample positions are never used for electrical rematching.</p>
  </div>;
}
