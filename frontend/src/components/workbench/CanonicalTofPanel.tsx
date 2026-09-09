import { useQuery } from "@tanstack/react-query";
import { client } from "../../api/client";
import { BlockedValue } from "./shared";
import { numberText } from "../../lib/presentation";

/** BRW-017R2 — canonical envelope-peak surface→bottom TOF panel.
 *
 * Displays method identity, gate ids, per-frame peak indices, Δsamples and
 * tof_us exactly as reported by the backend; fs provenance is the Parameter
 * Registry. XCorr is diagnostic-only and never shown as canonical tof_us.
 */
export function CanonicalTofPanel({
  batteryId,
  experimentId,
}: {
  batteryId: string;
  experimentId: string;
}) {
  const tof = useQuery({
    queryKey: ["canonical-tof", batteryId, experimentId],
    queryFn: () => client.getCanonicalTof(batteryId, experimentId, 200),
  });
  if (tof.isLoading) return null;
  if (tof.error) return null;
  const d = tof.data?.data;
  if (!d) return null;
  const audit = d.audit;
  const activated = d.sampling_rate_verified && audit.canonical_tof_valid > 0;
  const first = d.rows[0];

  return (
    <section className="panel mt-6" data-testid="canonical-tof-panel">
      <div className="flex flex-wrap gap-2 items-center justify-between">
        <h3 className="text-sm font-medium">规范 TOF · 包络峰值 表面波 → 底波</h3>
        <span className="text-xs muted">{d.tof_method_id} · v{first?.tof_definition_version}</span>
      </div>
      <div className="grid md:grid-cols-3 panel !p-0 mt-3 border-0">
        <BlockedValue
          name="Surface 峰值采样点"
          value={activated ? first?.surface_peak_sample_index : null}
          reason={activated ? `闸门 ${d.surface_gate_id}` : "需要已验证 fs + 冻结双闸门"}
        />
        <BlockedValue
          name="Bottom 峰值采样点"
          value={activated ? first?.bottom_peak_sample_index : null}
          reason={activated ? `闸门 ${d.bottom_gate_id}` : "需要已验证 fs + 冻结双闸门"}
        />
        <BlockedValue
          name="Δ样本 → tof_us"
          value={activated ? first?.tof_samples : null}
          unit={activated ? "samples" : undefined}
          reason={
            activated && first?.tof_us != null
              ? `${numberText(first.tof_us, 2)} µs @ ${numberText((d.sampling_rate_hz ?? 0) / 1e6, 0)} MHz`
              : d.sampling_rate_verified
                ? "fs 已验证；等待双闸门冻结"
                : "需要先以 verified 方式录入采样频率"
          }
        />
      </div>
      <p className="text-xs muted mt-2" data-testid="canonical-tof-audit">
        {audit.total_frames} 帧 · 状态分布 {JSON.stringify(audit.status_counts)}
        {audit.tof_us_stats
          ? ` · tof_us ${numberText(audit.tof_us_stats.min, 2)}–${numberText(audit.tof_us_stats.max, 2)} µs（中位 ${numberText(audit.tof_us_stats.median, 2)}）`
          : ""}
        {" · "}fs 仅来自参数注册表；XCorr 仅作诊断，不进入规范 tof_us。
      </p>
    </section>
  );
}
