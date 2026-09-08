import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams, Link } from "react-router-dom";
import { ArrowRight, Check, FlaskConical, ShieldCheck, TriangleAlert } from "lucide-react";
import { client, type CorrelationResultEntry, type FeatureInfo } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Checkbox } from "../../components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { PageHeader, LoadingState, ErrorState, ScopeNote } from "../../components/workbench/shared";
import { ParameterDialog } from "../../components/workbench/ParameterDialog";
import { FeatureCatalogue } from "../../components/workbench/FeatureCatalogue";
import { displayName, numberText } from "../../lib/presentation";

const CORE = ["amplitude_a_u", "tof_us", "wave_speed_m_s"];

export function FeatureCard({ feature, selected, toggle }: { feature: FeatureInfo; selected: boolean; toggle: () => void }) {
  const available = feature.availability === "AVAILABLE";
  const reason = feature.feature_name === "tof_us" ? "Sampling rate required"
    : feature.feature_name === "wave_speed_m_s" ? "Acoustic path and capability required"
    : "Not available in this experiment";
  return <div className="feature-card" data-selected={selected}><div className="flex items-start gap-3"><Checkbox aria-label={`Select ${displayName(feature.feature_name)}`} checked={selected} disabled={!available} onCheckedChange={toggle} /><div className="flex-1"><h3>{displayName(feature.feature_name)}</h3><p className="text-xs muted mt-1">{available ? "Available for inspection" : reason}</p></div>{selected && <Check size={15} className="text-primary" />}</div><div className="mt-5">{available ? <Badge variant="secondary">Available</Badge> : feature.feature_name === "tof_us" ? <ParameterDialog /> : <Badge variant="outline">Unavailable</Badge>}</div></div>;
}

function scopeLabel(scope: string): string {
  return scope === "overall" ? "总体 / Overall" : scope === "charge" ? "充电 / Charge"
    : scope === "discharge" ? "放电 / Discharge" : scope === "rest" ? "静置 / Rest" : scope;
}

function CorrelationTable({ rows }: { rows: CorrelationResultEntry[] }) {
  const methods = ["pearson", "spearman"];
  const scopes = ["overall", "charge", "discharge", "rest"];
  return <div className="overflow-x-auto" data-testid="soc-correlation-table">
    <table className="w-full text-sm"><thead><tr className="text-left muted text-xs">
      <th className="py-2 pr-4">View / 视图</th><th className="py-2 pr-4">Pearson / 皮尔逊</th><th className="py-2 pr-4">Spearman / 斯皮尔曼</th><th className="py-2 pr-4">n</th><th className="py-2">说明</th>
    </tr></thead><tbody>
      {scopes.map(scope => {
        const row = (method: string) => rows.find(r => r.scope === scope && r.method === method);
        const p = row("pearson"); const s = row("spearman");
        return <tr key={scope} className="border-t">
          <td className="py-2 pr-4">{scopeLabel(scope)}</td>
          <td className="py-2 pr-4 tabular-nums">{p?.coefficient != null ? numberText(p.coefficient, 3) : "—"}</td>
          <td className="py-2 pr-4 tabular-nums">{s?.coefficient != null ? numberText(s.coefficient, 3) : "—"}</td>
          <td className="py-2 pr-4 tabular-nums">{p?.n_valid ?? 0}</td>
          <td className="py-2 text-xs muted">{p?.status !== "VALID" ? p?.status.replace(/_/g, " ") : ""}</td>
        </tr>;
      })}
    </tbody></table>
    <p className="text-xs muted mt-2">{methods.join(" / ")} · Reference SOC / 参考 SOC · 无显著性 p 值（波形帧存在时间自相关）/ No naive p-values: frames are temporally correlated.</p>
  </div>;
}

function FeatureRelationship() {
  const { batteryId = "", experimentId = "" } = useParams();
  const [featureCode, setFeatureCode] = useState("SWA");
  const corr = useQuery({
    queryKey: ["feature-correlations", batteryId, experimentId, featureCode],
    queryFn: () => client.getFeatureCorrelations(batteryId, experimentId, featureCode, 4000),
  });
  const options = [
    { code: "SWA", label: "SWA / 表面波幅值" },
    { code: "BOTTOM_AMP", label: "Bottom-wave Amplitude / 底波幅值" },
  ];
  const data = corr.data?.data;
  const sohLimited = data?.soh.status === "NOT_READY_INSUFFICIENT_SOH_STATES";
  const tempBlocked = data?.temperature.status === "INSUFFICIENT_VARIATION" || data?.temperature.status === "TEMPERATURE_UNAVAILABLE";
  return <section className="panel mt-8" data-testid="feature-relationship">
    <h2 className="flex gap-3 items-center">Feature Relationship / 特征关系</h2>
    <p className="muted text-sm mt-2">后端在同一 MeasurementEvent 电学上下文上计算相关性；前端不重算任何指标。</p>
    <div className="mt-4 flex flex-wrap gap-2 items-center" role="group" aria-label="选择特征">
      <span className="text-sm muted">Feature / 特征:</span>
      {options.map(o => <Button key={o.code} size="sm" variant={featureCode === o.code ? "secondary" : "ghost"}
        aria-pressed={featureCode === o.code} onClick={() => setFeatureCode(o.code)}>{o.label}</Button>)}
    </div>
    {corr.isLoading && <LoadingState />}
    {corr.error && <ErrorState error={corr.error} retry={() => void corr.refetch()} />}
    {data && <>
      <h3 className="mt-6 mb-2">Correlation with Reference SOC / 与参考 SOC 的相关性</h3>
      <CorrelationTable rows={data.soc} />
      <div className="grid md:grid-cols-2 gap-4 mt-6">
        <div className="feature-card" data-testid="temperature-analysis">
          <h3>Temperature / 温度</h3>
          {tempBlocked ? <p className="text-sm mt-2"><TriangleAlert size={15} className="inline mr-1" />
            {data.temperature.status === "TEMPERATURE_UNAVAILABLE" ? "本实验无温度通道。/ No temperature channel in this experiment." : "温度变化不足（INSUFFICIENT_VARIATION），不报告相关系数。"}</p>
            : <p className="text-sm mt-2">Pearson {numberText(data.temperature.coefficient, 3)} · n = {data.temperature.n_valid}</p>}
          <p className="text-xs muted mt-2">Range / valid / missing 由后端报告；缺失保持为空，不插补。</p>
        </div>
        <div className="feature-card" data-testid="soh-analysis">
          <h3>SOH / 健康状态</h3>
          {sohLimited && <p className="text-sm mt-2"><TriangleAlert size={15} className="inline mr-1" />
            仅 {new Set(data.soh_cycle_summary.map(s => s.soh_percent)).size} 个独立 SOH 状态 — 相关性不适用（limited）。</p>}
          <table className="w-full text-xs mt-3"><thead><tr className="text-left muted"><th className="py-1">Cycle / 循环</th><th className="py-1">SOH</th><th className="py-1">n frames</th><th className="py-1">Feature median</th></tr></thead>
            <tbody>{data.soh_cycle_summary.map(s => <tr key={s.cycle} className="border-t">
              <td className="py-1">{s.cycle}</td><td className="py-1 tabular-nums">{numberText(s.soh_percent, 2)}</td>
              <td className="py-1 tabular-nums">{s.n_frames}</td><td className="py-1 tabular-nums">{numberText(s.feature_median, 2)}</td></tr>)}</tbody></table>
          <p className="text-xs muted mt-2">SOH 为 cycle 级，不做 frame 级相关性解读。</p>
        </div>
      </div>
    </>}
  </section>;
}

export function AnalysisWorkbench() {
  const { batteryId = "", experimentId = "" } = useParams();
  const [mode, setMode] = useState<"EXPLORATORY_FULL_DATA" | "TRAIN_ONLY_ML_SAFE">("EXPLORATORY_FULL_DATA");
  const [selected, setSelected] = useState<string[]>([]); const [action, setAction] = useState<"analysis" | "dataset" | null>(null); const [analysisId, setAnalysisId] = useState<string | null>(null);
  const features = useQuery({ queryKey: ["features", batteryId, experimentId], queryFn: () => client.listFeatures(batteryId, experimentId) });
  const analysis = useQuery({ queryKey: ["feature-analysis", analysisId], queryFn: () => client.getFeatureAnalysis(analysisId!), enabled: !!analysisId });
  const materialized = useQuery({ queryKey: ["materialized-analyses", batteryId, experimentId], queryFn: () => client.listMaterializedAnalyses(batteryId, experimentId) });
  // TRAIN_ONLY_ML_SAFE: use a materialized analysis whose split is ready and
  // whose selected features overlap the user selection (backend-authoritative).
  const readyAnalysis = mode === "TRAIN_ONLY_ML_SAFE"
    ? (materialized.data?.data.analyses ?? []).find(a =>
        a.status === "AVAILABLE" && a.split_id
        && a.selected_features.some(f => selected.includes(f)))
    : null;
  const run = useMutation({ mutationFn: () => client.createFeatureAnalysis({ battery_id: batteryId, experiment_id: experimentId, analysis_mode: mode, target: "soc_reference_percent", candidate_features: selected, ...(mode === "TRAIN_ONLY_ML_SAFE" && readyAnalysis ? { split_id: readyAnalysis.split_id!, fold_index: readyAnalysis.fold_index! } : {}) }), onSuccess: r => { setAction(null); setAnalysisId(r.data.analysis_id); } });
  const dataset = useMutation({ mutationFn: () => client.createDataset({ battery_id: batteryId, experiment_id: experimentId, dataset_family: "SOC", target: "soc_reference_percent", selected_features: selected }), onSuccess: () => setAction(null) });
  const mlSafeBlocked = mode === "TRAIN_ONLY_ML_SAFE" && !readyAnalysis && !analysisId;
  const all = features.data?.data.features ?? [];
  const core = CORE.map(name => all.find(f => f.feature_name === name) ?? { feature_name: name, availability: "UNAVAILABLE", role: null, gate_id: null, tof_definition_id: null, missing_reason: null });
  const hasMovmean5 = useMemo(() => selected.some(s => s.toLowerCase().includes("movmean")), [selected]);
  function toggle(name: string) { setSelected(prev => prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]); setAnalysisId(null); dataset.reset(); }
  if (features.isLoading) return <LoadingState />;
  if (features.error) return <ErrorState error={features.error} retry={() => void features.refetch()} />;
  return <><PageHeader eyebrow="Understand your signals" title="Analysis" description="Explore relationships with reference SOC, or prepare a leakage-safe selection." />
    <fieldset className="mb-8"><legend className="font-medium mb-3">Analysis mode / 分析模式</legend><div className="grid md:grid-cols-2 gap-4">
      {([{ value: "EXPLORATORY_FULL_DATA", title: "探索数据关系 / Explore Relationships", description: "使用全部可用数据进行科学探索。", icon: FlaskConical }, { value: "TRAIN_ONLY_ML_SAFE", title: "为建模选择特征 / Select Features for Modeling", description: "仅使用训练组数据，避免数据泄漏（TRAIN_ONLY_ML_SAFE）。", icon: ShieldCheck }] as const).map(m => <label key={m.value} className={`panel flex items-start gap-3 cursor-pointer ${mode === m.value ? "!border-primary !bg-[#f3f7f6]" : ""}`}><input type="radio" name="analysis-mode" className="mt-1 accent-[#385c66]" checked={mode === m.value} onChange={() => { setMode(m.value); setAnalysisId(null); dataset.reset(); }} /><div><h3 className="flex gap-2 items-center"><m.icon size={17} />{m.title}</h3><p className="text-sm muted mt-2">{m.description}</p></div></label>)}
    </div></fieldset>
    <div className="flex justify-between items-center mb-4"><h2>核心特征 / Core</h2><span className="text-sm muted">已选 {selected.length} 个</span></div><div className="grid md:grid-cols-3 gap-4">{core.map(f => <FeatureCard key={f.feature_name} feature={f} selected={selected.includes(f.feature_name)} toggle={() => toggle(f.feature_name)} />)}</div>
    <details className="mt-4 mb-8" data-testid="more-features" open>
      <summary>更多特征 / More features · 来自特征定义目录（API）</summary>
      <div className="mt-3"><FeatureCatalogue selected={selected} onToggle={toggle} availableNames={all.filter(f => f.availability === "AVAILABLE").map(f => f.feature_name)} /></div>
    </details>
    <FeatureRelationship />
    <section className="panel mt-8"><div className="flex flex-wrap gap-4 justify-between items-center"><div><h2>{mode === "EXPLORATORY_FULL_DATA" ? "探索模式不能直接用于建模" : "选择保留在训练组内"}</h2><p className="muted text-sm mt-2">{mode === "EXPLORATORY_FULL_DATA" ? "探索性排序不能作为无偏建模选择复用。" : "HELD_OUT 组在特征选择与拟合期间不可访问。"}</p>
      {hasMovmean5 && <p className="notice text-sm mt-3" role="alert"><TriangleAlert size={15} className="inline mr-1" />movmean5 平滑变体仅用于探索 / Exploratory only — 全局平滑可跨折边界泄漏，不能作为 ML-safe 预测器提交。</p>}
    </div><Button disabled={!selected.length} onClick={() => { run.reset(); setAction("analysis"); }}>Review analysis<ArrowRight /></Button></div>
      {analysisId && <div role="status" className="notice mt-4">{analysis.isLoading ? "Checking analysis availability…" : analysis.error ? "Specification resolved, but analysis results are not available. No values or ranking have been inferred." : "Analysis is available. This API currently provides status only; correlation details are not exposed."}</div>}
      <div className="mt-5 flex flex-wrap gap-3 items-center"><Button variant="outline" disabled={mode !== "TRAIN_ONLY_ML_SAFE" || !selected.length || !(analysis.data?.data.status === "AVAILABLE" || readyAnalysis)} onClick={() => { dataset.reset(); setAction("dataset"); }}>Build dataset with {selected.length} features / 用所选特征构建数据集</Button>
        {mode === "TRAIN_ONLY_ML_SAFE" && readyAnalysis && <p className="text-xs muted w-full" role="status" data-testid="ml-safe-analysis-found">已找到匹配的 ML-safe 分析（split 就绪，选择保留在训练组内）。/ Matching ML-safe analysis found.</p>}
        {mlSafeBlocked && <p className="text-xs muted w-full" role="status">Select Features 模式需要一个已就绪的 grouped split 与特征分析；请先在 Advanced → Splits 完成。</p>}<Button variant="link" asChild><Link to={`/experiments/${batteryId}/${experimentId}/advanced/runs`}>Review pending scientific actions</Link></Button></div>
      <p className="text-xs muted mt-2">Dataset creation requires an available ML-safe analysis and explicit confirmation. Backend eligibility remains authoritative.</p>
      {dataset.isSuccess && <div className="notice mt-3" role="status" data-testid="dataset-handoff"><p>数据集请求完成。/ Dataset request completed.</p><p className="text-sm mt-1">下一步：在 <Link className="underline" to={`/experiments/${batteryId}/${experimentId}/advanced/splits`}>Advanced → Splits</Link> 创建 grouped split（按 cycle 分组，防泄漏）。</p></div>}
    </section><ScopeNote />
    <Dialog open={action !== null} onOpenChange={open => { if (!open) setAction(null); }}><DialogContent><DialogHeader><DialogTitle>{action === "dataset" ? "用所选特征构建数据集" : "确认分析请求"}</DialogTitle><DialogDescription>{batteryId} / {experimentId} · {mode === "TRAIN_ONLY_ML_SAFE" ? "仅训练组选择" : "探索性分析"}。此科学操作将使用下方所选输入。</DialogDescription></DialogHeader><ul className="list-disc pl-5">{selected.map(n => <li key={n}>{n.startsWith("TD") || n.startsWith("FD") || ["SWA", "BOTTOM_AMP", "TOF_XCORR", "ATTENUATION", "BPS"].includes(n) ? n : displayName(n)}</li>)}</ul><p className="text-sm muted">你的确认仅授权本次请求。不会发生自动特征选择或模型训练。</p>{(run.error || dataset.error) && <p role="alert">服务无法接受此请求，请检查前置条件后重试。</p>}<DialogFooter><Button variant="outline" onClick={() => setAction(null)}>取消</Button><Button disabled={run.isPending || dataset.isPending} onClick={() => action === "dataset" ? dataset.mutate() : run.mutate()}>确认请求</Button></DialogFooter></DialogContent></Dialog>
  </>;
}
