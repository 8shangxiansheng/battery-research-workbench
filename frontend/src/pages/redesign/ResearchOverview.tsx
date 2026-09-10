/**
 * BRW-025R-OV — Research Overview：科研工作台首屏。
 *
 * 单一聚合数据源（GET /research-overview）；前端不做任何科学计算。
 * 只读首屏：不改科学工件；inline fs 配置复用 BRW-018R2 共享提交服务。
 * 高信息密度、低视觉噪声；Quick Actions ≤3 由后端 readiness 生成。
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, Battery, MessageSquare, RefreshCw, Waves } from "lucide-react";
import { client } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Input } from "../../components/ui/input";
import { Checkbox } from "../../components/ui/checkbox";
import { LoadingState, ErrorState } from "../../components/workbench/shared";
import { useAssistant } from "../../components/workbench/AssistantContext";
import { useSamplingSubmission, type SubmissionState } from "../../lib/submission";
import { numberText } from "../../lib/presentation";

const META_LABELS: Record<string, string> = {
  Battery: "电池", Experiment: "实验", Chemistry: "化学体系",
  "Nominal Capacity": "标称容量", Probe: "探头", "Sampling Rate": "采样频率",
  Temperature: "温度", Channel: "通道", Date: "采集日期", Timebase: "时间基准",
};

function MetaItem({ label, entry, format }: {
  label: string;
  entry: { status: string; value?: unknown; hz?: number | null; verified?: boolean; channel?: string[] | null; range_c?: [number, number]; start?: string | null; end?: string | null };
  format?: (v: unknown) => string;
}) {
  const available = entry.status === "AVAILABLE";
  const display = available
    ? (format ? format(entry) : String(entry.value ?? "—"))
    : entry.status === "PROVISIONAL" ? "临时基准" : "未配置";
  return <div className="meta-item" data-testid={`meta-${label}`}>
    <span className="muted">{META_LABELS[label] ?? label}</span>
    <span className={`text-sm font-medium ${available ? "" : "muted"}`}>{display}</span>
    {label === "Sampling Rate" && available && entry.verified && <Badge variant="outline" className="text-[10px]">已验证</Badge>}
  </div>;
}

function InlineFsConfig({ batteryId, experimentId }: { batteryId: string; experimentId: string }) {
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState<"Hz" | "kHz" | "MHz">("MHz");
  const [source, setSource] = useState("");
  const [verified, setVerified] = useState(false);
  const [state, setState] = useState<SubmissionState | null>(null);
  const { submit, retryResume } = useSamplingSubmission();
  const numeric = Number(value);
  const valid = value.trim() !== "" && Number.isFinite(numeric) && numeric > 0 && source.trim().length > 0;
  const saving = state?.phase === "SAVING";

  async function run() {
    if (!valid) return;
    await submit(
      { batteryId, experimentId, value: numeric, unit, source: source.trim(), verified },
      setState,
    );
  }
  if (state && (state.phase === "SAVED" || state.phase === "PARTIAL")) {
    return <div className="space-y-2" data-testid="ov-fs-result">
      <p role="status" className="notice !py-2 text-sm" data-testid="ov-fs-saved">✓ {state.message}</p>
      {state.phase === "PARTIAL" && (
        <Button variant="outline" size="sm" data-testid="ov-fs-retry" disabled={saving}
          onClick={() => state.submissionId && retryResume(batteryId, experimentId, state.submissionId, setState)}>
          重试恢复
        </Button>
      )}
    </div>;
  }
  return <div className="space-y-2" data-testid="ov-fs-config">
    <div className="flex gap-2 items-end flex-wrap">
      <label className="text-xs muted flex-1 min-w-[8rem]">数值
        <Input data-testid="ov-fs-value" type="number" min="0" step="any" value={value}
          onChange={e => setValue(e.target.value)} placeholder="采样频率" className="mt-1"/>
      </label>
      <label className="text-xs muted w-20">单位
        <select data-testid="ov-fs-unit" className="w-full mt-1" value={unit}
          onChange={e => setUnit(e.target.value as "Hz" | "kHz" | "MHz")}>
          <option>Hz</option><option>kHz</option><option>MHz</option>
        </select>
      </label>
    </div>
    <label className="text-xs muted block">来源（仪器记录；禁止从节奏/采样点数/文件名猜测）
      <Input data-testid="ov-fs-source" value={source} onChange={e => setSource(e.target.value)}
        placeholder="e.g. acquisition configuration" className="mt-1"/>
    </label>
    <label className="flex gap-2 items-center text-xs">
      <Checkbox data-testid="ov-fs-verified" checked={verified} onCheckedChange={v => setVerified(!!v)}/>
      我确认这是仪器记录值（已验证）
    </label>
    <div className="flex gap-2 items-center">
      <Button size="sm" data-testid="ov-fs-save" disabled={!valid || saving} onClick={() => void run()}>
        {saving ? "保存中…" : "保存"}
      </Button>
      {state?.phase === "FAILED" && <span role="alert" className="text-xs text-red-700" data-testid="ov-fs-failed">✗ {state.message}</span>}
    </div>
  </div>;
}

function Sparkline({ values, color, label }: { values: (number | null)[]; color: string; label: string }) {
  const nums = values.filter((v): v is number => v != null);
  if (nums.length < 2) return null;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const w = 220;
  const h = 36;
  const step = w / (nums.length - 1);
  const path = nums.map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(h - ((v - min) / span) * h).toFixed(1)}`).join(" ");
  return <svg width={w} height={h} role="img" aria-label={label} className="max-w-full">
    <path d={path} fill="none" stroke={color} strokeWidth="1.4"/>
  </svg>;
}

const READINESS_LABELS: Record<string, string> = {
  READY: "就绪", BLOCKED: "阻断", LIMITED: "受限", PROVISIONAL: "临时基准",
  READY_FOR_LIMITED_EVALUATION: "受限评估", UNAVAILABLE: "不可用",
  NOT_CONFIGURED: "未配置",
};

const READINESS_FIELD_LABELS: Record<string, string> = {
  acquisition: "数据采集", synchronization: "同步对齐", tof: "TOF 飞行时间",
  targets: "研究目标", modeling: "建模评估",
};

export function ResearchOverview() {
  const { batteryId = "", experimentId = "" } = useParams();
  const assistant = useAssistant();
  const overview = useQuery({
    queryKey: ["research-overview", batteryId, experimentId],
    queryFn: () => client.getResearchOverview(batteryId, experimentId),
  });
  if (overview.isPending) return <LoadingState/>;
  if (overview.isError) return <ErrorState error={overview.error} retry={() => void overview.refetch()}/>;
  const d = overview.data.data;
  const base = `/experiments/${batteryId}/${experimentId}`;
  const tof = d.ultrasound_tof;
  const banner = d.research_status_banner;

  function askWithOverviewContext() {
    // Requirement 16: inject experiment/readiness/target/TOF/model/limitations
    const ctx = [
      `实验 ${batteryId}/${experimentId}`,
      `Readiness: acquisition=${d.readiness_matrix.acquisition}, sync=${d.readiness_matrix.synchronization}, TOF=${d.readiness_matrix.tof}, targets=${d.readiness_matrix.targets}, modeling=${d.readiness_matrix.modeling}`,
      `Target: ${d.scientific_snapshot.target.target_id} (${d.scientific_snapshot.target.readiness})`,
      `TOF: fs=${tof.sampling_rate_hz ?? "unknown"}Hz verified=${tof.sampling_rate_verified}, calibration=${tof.gate_calibration_id} (${tof.gate_calibration_source} v${tof.gate_calibration_version})`,
      `Model: ${d.model_comparison.dummy_first_conclusion ?? "尚无对比结论"}（Dummy MAE ${numberText(d.model_comparison.dummy?.macro_mae)}）`,
      `限制: ${d.limitations_first_screen.map(l => l.code).join(", ")}`,
    ].join("；");
    assistant.ask(`请基于当前科研状态解读这个实验。${ctx}`);
  }

  return <div className="research-overview space-y-4" data-testid="research-overview">
    {/* Research Status Banner */}
    <section className={`pipeline-card ${banner.level === "BLOCKED" ? "state-warning" : ""}`} data-testid="research-status-banner" aria-live="polite">
      <div className="flex items-start gap-3 justify-between flex-wrap">
        <div>
          <p className="eyebrow">科研状态 / Research Status</p>
          <h2 className="text-lg">{banner.message}</h2>
        </div>
        <Button variant="ghost" data-testid="ask-assistant-with-context" onClick={askWithOverviewContext}>
          <MessageSquare size={15}/>携带科研上下文询问助手
        </Button>
      </div>
    </section>

    {/* Metadata Strip */}
    <section className="panel !py-3" data-testid="metadata-strip">
      <div className="flex flex-wrap gap-x-8 gap-y-2">
        <MetaItem label="Battery" entry={{ status: "AVAILABLE", value: d.metadata.battery_id }}/>
        <MetaItem label="Experiment" entry={{ status: "AVAILABLE", value: d.metadata.experiment_id }}/>
        <MetaItem label="Chemistry" entry={d.metadata.chemistry}/>
        <MetaItem label="Nominal Capacity" entry={{ status: d.metadata.nominal_capacity_ah.status,
          value: d.metadata.nominal_capacity_ah.value != null ? `${d.metadata.nominal_capacity_ah.value} Ah` : null }}/>
        <MetaItem label="Probe" entry={d.metadata.probe}/>
        <MetaItem label="Sampling Rate" entry={{ status: d.metadata.sampling_rate.status,
          value: d.metadata.sampling_rate.hz != null ? `${numberText((d.metadata.sampling_rate.hz ?? 0) / 1e6, 0)} MHz` : null,
          verified: d.metadata.sampling_rate.verified }}/>
        <MetaItem label="Temperature" entry={{ status: d.metadata.temperature.status,
          value: d.metadata.temperature.channel ? `${d.metadata.temperature.channel.join("/")} ${d.metadata.temperature.range_c?.[0]}–${d.metadata.temperature.range_c?.[1]}°C` : null }}/>
        <MetaItem label="Channel" entry={{ status: d.metadata.channel.status }}/>
        <MetaItem label="Date" entry={{ status: d.metadata.acquisition_window.start ? "AVAILABLE" : "NOT_CONFIGURED",
          value: d.metadata.acquisition_window.start?.slice(0, 10) }}/>
        <MetaItem label="Timebase" entry={{ status: "PROVISIONAL", value: d.metadata.timebase.status }}/>
      </div>
    </section>

    {/* Snapshots row */}
    <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))" }}>
      <section className="panel !p-5" data-testid="electrical-snapshot">
        <div className="flex justify-between items-center">
          <h2 className="flex gap-2 items-center"><Battery size={16}/>电学快照</h2>
          <Badge variant="outline">{d.electrical.status}</Badge>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
          <span className="muted">记录数</span><span className="font-mono">{numberText(d.electrical.record_count, 0)}</span>
          <span className="muted">循环 / 工步</span><span className="font-mono">{numberText(d.electrical.cycle_count, 0)} / {numberText(d.electrical.step_count, 0)}</span>
          <span className="muted">电压范围</span><span className="font-mono">{d.electrical.voltage_range_v?.[0]} – {d.electrical.voltage_range_v?.[1]} V</span>
          <span className="muted">电流范围</span><span className="font-mono">{d.electrical.current_range_a?.[0]} – {d.electrical.current_range_a?.[1]} A</span>
        </div>
        <div className="mt-2 flex gap-4 flex-wrap">
          <Sparkline values={d.electrical.voltage_sparkline_v} color="#334155" label="电压 sparkline"/>
          <Sparkline values={d.electrical.current_sparkline_a} color="#0d9488" label="电流 sparkline"/>
        </div>
        <table className="mt-2 w-full text-xs" data-testid="electrical-cycles">
          <thead><tr><th className="text-left muted">循环</th><th className="text-right muted">充电容量 Ah</th><th className="text-right muted">放电容量 Ah</th><th className="text-right muted">表观库仑效率</th></tr></thead>
          <tbody>{d.electrical.cycles.map(c => <tr key={c.cycle_index_raw}>
            <td>{c.cycle_index_raw}</td>
            <td className="text-right font-mono">{numberText(c.charge_capacity_ah, 3)}</td>
            <td className="text-right font-mono">{numberText(c.discharge_capacity_ah, 3)}</td>
            <td className="text-right font-mono">{numberText(c.apparent_coulombic_efficiency_percent, 2)}%</td>
          </tr>)}</tbody>
        </table>
        <p className="text-[10px] muted mt-1">表观库仑效率 = 解析器报告的 coulombic_efficiency_percent（仅 2 循环，非长期库仑效率结论）。{d.electrical.cycles[0]?.protocol === "PROTOCOL_FROM_PARSER" ? "协议：解析器记录。" : ""}</p>
      </section>

      <section className="panel !p-5" data-testid="tof-snapshot">
        <div className="flex justify-between items-center">
          <h2 className="flex gap-2 items-center"><Waves size={16}/>超声 / TOF 快照</h2>
          <Badge variant={tof.status === "READY" ? "secondary" : "outline"}>{tof.status}</Badge>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
          <span className="muted">规范方法</span>
          <span className="font-mono text-xs truncate" title={tof.tof_method_id}>{tof.tof_method_id}</span>
          <span className="muted">采样频率来源</span>
          <span className="font-mono text-xs">{tof.sampling_rate_hz != null ? `${numberText(tof.sampling_rate_hz / 1e6, 0)} MHz` : "—"}{tof.sampling_rate_verified ? " · 已验证" : " · 未验证"}</span>
          <span className="muted">闸门标定</span>
          <span className="font-mono text-xs truncate" title={tof.gate_calibration_id}>{tof.gate_calibration_source} v{tof.gate_calibration_version}</span>
          <span className="muted">表面波闸门</span><span className="font-mono text-xs">{tof.surface_gate_id} [{tof.surface_peak_sample_range[0]},{tof.surface_peak_sample_range[1]})</span>
          <span className="muted">底波闸门</span><span className="font-mono text-xs">{tof.bottom_gate_id} [{tof.bottom_peak_sample_range[0]},{tof.bottom_peak_sample_range[1]})</span>
          <span className="muted">TOF（当前工件）</span>
          <span className="font-mono text-xs">{tof.artifact_tof_us_summary ? `${tof.artifact_tof_us_summary.min}–${tof.artifact_tof_us_summary.max} µs` : "—"}</span>
        </div>
        <div className="mt-2 text-xs muted" data-testid="tof-coverage">
          覆盖范围区分：波形 TOF 行 {numberText(tof.waveform_tof.event_count, 0)}（歧义 {numberText(tof.waveform_tof.ambiguous_events, 0)}） ≠ 特征–目标可用行 {numberText(tof.feature_target_eligible.eligible_count, 0)}
        </div>
        <p className="text-[10px] muted mt-1">
          当前校准定义与 fs/registry {tof.artifact_current ? "一致" : "不一致（需要刷新）——canonical TOF 工件需重算"}。
          {/* A-scan + peaks 图形预览在波形工作台；此处保持低噪声 */}
        </p>
      </section>
    </div>

    {/* Readiness matrix + Quick actions */}
    <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))" }}>
      <section className="panel !p-5" data-testid="readiness-matrix">
        <h2>科研就绪度矩阵</h2>
        <div className="mt-3 space-y-1.5 text-sm">
          {Object.entries(d.readiness_matrix).map(([k, v]) => <div key={k} className="flex justify-between items-center">
            <span className="muted">{READINESS_FIELD_LABELS[k] ?? k}</span>
            <Badge variant={v === "READY" ? "secondary" : v === "LIMITED" || v.startsWith("READY_FOR") || v === "PROVISIONAL" ? "outline" : "destructive"}
              data-testid={`readiness-${k}`}>{READINESS_LABELS[v] ?? v}</Badge>
          </div>)}
        </div>
      </section>
      <section className="panel !p-5" data-testid="quick-actions">
        <h2>快捷操作</h2>
        <div className="mt-3 space-y-2">
          {d.next_actions.map(a => <Button key={a.action_id} variant="outline" size="sm" asChild className="w-full justify-between" data-testid={`quick-action-${a.action_id}`}>
            <Link to={a.route.replace(`/experiments/${batteryId}/${experimentId}`, base)}>{a.label}<ArrowRight size={14}/></Link>
          </Button>)}
        </div>
        <h2 className="mt-4">当前限制（首屏可见）</h2>
        <ul className="mt-2 space-y-1 text-xs muted" data-testid="limitations-first-screen">
          {d.limitations_first_screen.map(l => <li key={l.code}>• {l.description_zh ?? l.description}</li>)}
        </ul>
      </section>
    </div>

    {/* Scientific snapshot + fs inline config */}
    <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))" }}>
      <section className="panel !p-5" data-testid="scientific-snapshot">
        <h2>科研快照</h2>
        <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
          <span className="muted">研究目标</span><span>{d.scientific_snapshot.target.target_id}（{d.scientific_snapshot.target.readiness}）</span>
          <span className="muted">领先探索候选</span>
          <span className="font-mono text-xs truncate" data-testid="leading-candidate">
            {d.scientific_snapshot.leading_exploratory_candidate
              ? `${d.scientific_snapshot.leading_exploratory_candidate.feature_name} · ${d.scientific_snapshot.leading_exploratory_candidate.method} ${d.scientific_snapshot.leading_exploratory_candidate.coefficient} (n=${numberText(d.scientific_snapshot.leading_exploratory_candidate.n, 0)})`
              : "尚无持久探索性分析工件"}
          </span>
          <span className="muted">已选特征</span><span className="font-mono text-xs">{d.scientific_snapshot.selected_features.join(", ") || "—"}</span>
          <span className="muted">TOF 就绪度</span><span>{READINESS_LABELS[tof.status] ?? tof.status}</span>
        </div>
      </section>

      <section className="panel !p-5" data-testid="fs-inline-config">
        <h2>采样频率配置</h2>
        {d.metadata.sampling_rate.status === "AVAILABLE" && d.metadata.sampling_rate.verified
          ? <p className="text-sm mt-2" data-testid="fs-configured">已验证：{numberText((d.metadata.sampling_rate.hz ?? 0) / 1e6, 0)} MHz（{d.metadata.sampling_rate.parameter_set_id}）。重新配置请到 <Link className="underline" to={`${base}/advanced/parameters`}>参数工作台</Link>。</p>
          : <div className="mt-2"><InlineFsConfig batteryId={batteryId} experimentId={experimentId}/></div>}
      </section>
    </div>

    {/* Model baseline comparison */}
    <section className="panel !p-5" data-testid="model-baseline-comparison">
      <div className="flex justify-between items-center flex-wrap gap-2">
        <h2>模型基线对比（Dummy 优先）</h2>
        {d.model_comparison.feature_definition.refresh_required && (
          <Badge variant="outline" className="text-[#9b782e]" data-testid="model-refresh-required">
            <RefreshCw size={11} className="mr-1"/>使用历史特征定义 · 需要刷新
          </Badge>
        )}
      </div>
      <table className="mt-3 w-full text-sm" data-testid="model-comparison-table">
        <thead><tr>
          <th className="text-left muted py-1">策略</th><th className="text-right muted">Macro MAE</th>
          <th className="text-right muted">相对 Dummy</th><th className="text-right muted">Macro R²</th>
          <th className="text-right muted">可用性</th>
        </tr></thead>
        <tbody>{d.model_comparison.strategies.map(s => <tr key={s.strategy} className={s.strategy === "DUMMY_MEAN" ? "font-medium" : ""}>
          <td className="py-1">{s.strategy}{s.strategy === "DUMMY_MEAN" && <span className="muted text-xs ml-1">（基准）</span>}</td>
          <td className="text-right font-mono">{numberText(s.macro_mae, 2)}</td>
          <td className="text-right font-mono">{s.vs_dummy != null ? `+${numberText(s.vs_dummy, 2)}` : "—"}</td>
          <td className="text-right font-mono">{numberText(s.macro_r2, 2)}</td>
          <td className="text-right text-xs muted">{s.strategy === "DUMMY_MEAN" ? "有效（当前结论依据）" : "可用（未用于当前结论）"}</td>
        </tr>)}</tbody>
      </table>
      <p className="text-xs muted mt-2" data-testid="model-evidence-note">
        {d.model_comparison.dummy_first_conclusion ?? "尚无同口径对比结论。"}
        {" "}当前模型工件使用 FS v{d.model_comparison.feature_definition.dataset_definition_version ?? "?"}（历史特征定义），从未使用 canonical 包络峰值 TOF；
        可用 / 有效 / 已选 / 已用 的区分见建模评估页。
      </p>
    </section>
  </div>;
}

