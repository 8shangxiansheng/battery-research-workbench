import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { client, type FeatureLabelPreviewResponse, type TargetDefinition } from "../../api/client";
import { PageHeader, LoadingState, ErrorState, ScopeNote } from "../../components/workbench/shared";
import { FeatureCatalogue } from "../../components/workbench/FeatureCatalogue";
import {
  TargetSelector, WorkflowStepper, type WorkflowStepKey,
} from "../../components/workbench/TargetSelector";
import {
  AlignmentSummary, AlignmentSamplesPanel, AlignmentExclusionsPanel,
} from "../../components/workbench/AlignmentPanels";
import { FeatureLabelTablePreview, TARGET_LABELS } from "../../components/workbench/FeatureLabelTable";
import { FeatureRankingTable } from "../../components/workbench/FeatureTargetWorkbench";
import { DatasetBuildButtons } from "../../components/workbench/DatasetXYPreview";

const PHYSICAL_FEATURES = ["BOTTOM_AMP", "SWA", "TOF_XCORR", "ATTEN_MAX", "BPS"];

export function AnalysisWorkbench() {
  const { batteryId = "", experimentId = "" } = useParams();
  // workflow state — target switch invalidates target-dependent artifacts only
  const [step, setStep] = useState<WorkflowStepKey>("target");
  const [targetId, setTargetId] = useState<string | null>(null);
  const [features, setFeatures] = useState<string[]>([]);
  const [mode, setMode] = useState<"EXPLORATORY_FULL_DATA" | "TRAIN_ONLY_ML_SAFE">("EXPLORATORY_FULL_DATA");
  const [built, setBuilt] = useState<"exploratory" | "mlsafe" | null>(null);

  const targets = useQuery({ queryKey: ["targets", batteryId, experimentId], queryFn: () => client.listTargets(batteryId, experimentId) });
  const target: TargetDefinition | undefined = (targets.data?.data.targets ?? []).find(t => t.target_id === targetId);
  const featuresLib = useQuery({ queryKey: ["features", batteryId, experimentId], queryFn: () => client.listFeatures(batteryId, experimentId) });
  const all = featuresLib.data?.data.features ?? [];
  const availableNames = useMemo(() => all.filter(f => f.availability === "AVAILABLE").map(f => f.feature_name), [all]);
  const materialized = useQuery({ queryKey: ["materialized-analyses", batteryId, experimentId], queryFn: () => client.listMaterializedAnalyses(batteryId, experimentId) });

  // preview data for dataset step (fetched once features+target chosen)
  const preview = useQuery({
    queryKey: ["feature-label-preview", batteryId, experimentId, targetId, features],
    queryFn: () => client.postFeatureLabelPreview(batteryId, experimentId, { target_id: targetId!, features, limit: 20 }),
    enabled: !!targetId && features.length > 0 && step === "dataset",
  });
  const summary: FeatureLabelPreviewResponse["summary"] | null = preview.data?.data.summary ?? null;

  const readyAnalysis = mode === "TRAIN_ONLY_ML_SAFE"
    ? (materialized.data?.data.analyses ?? []).find(a => a.status === "AVAILABLE" && a.split_id && a.selected_features.some(f => features.includes(f)))
    : null;

  function selectTarget(next: string) {
    if (next === targetId) return;
    // Target switch: reuse sync/features (kept in state), invalidate
    // target-dependent artifacts (target-specific query keys + draft)
    setTargetId(next);
    setBuilt(null);
  }
  function toggleFeature(code: string) {
    setFeatures(prev => prev.includes(code) ? prev.filter(f => f !== code) : [...prev, code]);
    setBuilt(null);
  }

  return <>
    <PageHeader eyebrow="Target-first workflow" title="特征分析" description="选择研究目标 → 检查同步对齐 → 浏览特征 → 分析关系 → 筛选 → 构建数据集。" />
    <WorkflowStepper current={step} onStep={setStep} />

    {step === "target" && <section data-testid="step-target">
      <TargetSelector batteryId={batteryId} experimentId={experimentId} selected={targetId} onSelect={selectTarget} />
      {targetId && <div className="notice mt-5 items-center" role="status">
        <div className="flex-1"><h3>已选择目标: {TARGET_LABELS[targetId] ?? targetId}</h3>
          <p className="text-sm">切换目标将复用同步与特征，仅失效目标相关的分析结果。</p></div>
        <button className="button" onClick={() => setStep("alignment")} data-testid="to-alignment">下一步: 对齐 / Next: Alignment →</button>
      </div>}
    </section>}

    {step === "alignment" && <section data-testid="step-alignment">
      <h2 className="text-xl">Synchronization & Alignment / 同步对齐</h2>
      <p className="muted text-sm mt-1">所有映射来自 canonical MeasurementEvent；禁止 gate/cycle/timestamp 重新匹配。</p>
      <AlignmentSummary batteryId={batteryId} experimentId={experimentId} targetId={targetId} />
      <AlignmentSamplesPanel batteryId={batteryId} experimentId={experimentId} />
      <AlignmentExclusionsPanel batteryId={batteryId} experimentId={experimentId} />
      <div className="mt-5 flex gap-3">
        <button className="button" onClick={() => setStep("target")}>← 上一步: 目标</button>
        <button className="button" onClick={() => setStep("features")} data-testid="to-features">下一步: 特征 →</button>
      </div>
    </section>}

    {step === "features" && <section data-testid="step-features">
      <h2 className="text-xl">Features / 特征</h2>
      <p className="muted text-sm mt-1">Ultrasound-derived features / 超声派生特征（来自 TXT waveform）。Target 来自 Electrical XLSX / label engine。不默认全部特征 × 全部闸门。</p>
      <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="物理特征快速选择">
        {PHYSICAL_FEATURES.map(f => <label key={f} className={`text-sm rounded-full border px-3 py-1 cursor-pointer ${features.includes(f) ? "border-primary bg-[#e9f1ef]" : ""}`}>
          <input type="checkbox" className="mr-1 accent-[#385c66]" checked={features.includes(f)} onChange={() => toggleFeature(f)} data-testid={`quick-${f}`} />{f}</label>)}
      </div>
      <details className="mt-4" open>
        <summary className="cursor-pointer">More features / 更多特征（完整目录）</summary>
        <div className="mt-3"><FeatureCatalogue selected={features} onToggle={toggleFeature} availableNames={availableNames} /></div>
      </details>
      <div className="mt-5 flex gap-3 items-center">
        <button className="button" onClick={() => setStep("alignment")}>← 上一步</button>
        <button className="button" disabled={!targetId} onClick={() => setStep("relationships")} data-testid="to-relationships">下一步: 关系 →</button>
        <span className="text-sm muted">已选 {features.length} 个特征</span>
      </div>
    </section>}

    {step === "relationships" && <section data-testid="step-relationships">
      <h2 className="text-xl">Feature–Target Relationship / 特征-目标关系</h2>
      <p className="muted text-sm mt-1">Target (y): <strong>{targetId ? TARGET_LABELS[targetId] : "未选择"}</strong> · 相关性全部由后端计算。</p>
      <div className="mt-4"><FeatureRankingTable batteryId={batteryId} experimentId={experimentId} targetId={targetId ?? "reference_soc_percent"} features={features} mode="EXPLORATORY" /></div>
      <div className="mt-5 flex gap-3">
        <button className="button" onClick={() => setStep("features")}>← 上一步</button>
        <button className="button" onClick={() => setStep("selection")} data-testid="to-selection">下一步: 筛选 →</button>
      </div>
    </section>}

    {step === "selection" && <section data-testid="step-selection">
      <h2 className="text-xl">Selection / 筛选</h2>
      <fieldset className="mt-4"><legend className="text-sm font-medium mb-2">Mode / 模式</legend>
        <div className="flex flex-wrap gap-3">
          <label className={`feature-card !p-3 cursor-pointer ${mode === "EXPLORATORY_FULL_DATA" ? "!border-primary" : ""}`}>
            <input type="radio" name="sel-mode" className="mr-2 accent-[#385c66]" checked={mode === "EXPLORATORY_FULL_DATA"} onChange={() => setMode("EXPLORATORY_FULL_DATA")} data-testid="mode-exploratory" />
            Explore / 探索 — 全部 eligible 数据，EXPLORATORY，非 ML-safe</label>
          <label className={`feature-card !p-3 cursor-pointer ${mode === "TRAIN_ONLY_ML_SAFE" ? "!border-primary" : ""}`}>
            <input type="radio" name="sel-mode" className="mr-2 accent-[#385c66]" checked={mode === "TRAIN_ONLY_ML_SAFE"} onChange={() => setMode("TRAIN_ONLY_ML_SAFE")} data-testid="mode-mlsafe" />
            Build for Modeling / 用于建模 — Grouped Split → TRAIN-only 分析 → 锁定特征 → held-out 评估</label>
        </div>
      </fieldset>
      {mode === "TRAIN_ONLY_ML_SAFE" && readyAnalysis && <p className="notice text-sm mt-3" role="status" data-testid="ml-safe-analysis-found">已找到匹配的 ML-safe 分析（split 就绪；held-out target 不可访问）。</p>}
      {mode === "TRAIN_ONLY_ML_SAFE" && !readyAnalysis && <p className="notice text-sm mt-3" role="status">ML-safe selection requires grouped split first. / 模型安全特征筛选需要先建立分组划分。请到 <Link className="underline" to={`/experiments/${batteryId}/${experimentId}/advanced/splits`}>Advanced → Splits</Link>。</p>}
      <div className="mt-4"><FeatureRankingTable batteryId={batteryId} experimentId={experimentId} targetId={targetId ?? "reference_soc_percent"} features={features} mode={mode === "TRAIN_ONLY_ML_SAFE" ? "TRAIN_ONLY_ML_SAFE" : "EXPLORATORY"} /></div>
      <div className="mt-5 flex gap-3">
        <button className="button" onClick={() => setStep("relationships")}>← 上一步</button>
        <button className="button" disabled={!features.length || !targetId} onClick={() => setStep("dataset")} data-testid="to-dataset">下一步: 数据集 →</button>
      </div>
    </section>}

    {step === "dataset" && <section data-testid="step-dataset">
      <h2 className="text-xl">Dataset / 数据集</h2>
      <p className="muted text-sm mt-1">Predictors (X) = 所选超声特征；Target (y) = {targetId ? TARGET_LABELS[targetId] : "—"}。先预览 X/y，再选择构建方式。</p>
      {preview.isLoading && <LoadingState />}
      {preview.error && <ErrorState error={preview.error} retry={() => void preview.refetch()} />}
      {summary && <div className="notice mt-4" data-testid="dataset-xy-inline">
        <p className="text-sm">Eligible rows / 可分析行: <strong className="tabular-nums">{summary.eligible_rows}</strong> · Excluded / 排除: {summary.excluded_rows} · Cycles: {summary.cycles.join(", ")}</p>
        <p className="text-xs muted mt-1">3999 → {summary.eligible_rows} 的行数漏斗由歧义同步与目标缺失解释，见 Alignment 步骤。</p>
      </div>}
      <div className="mt-4">
        <FeatureLabelTablePreview batteryId={batteryId} experimentId={experimentId} targetId={targetId ?? "reference_soc_percent"} features={features} />
      </div>
      <div className="mt-4">
        <DatasetBuildButtons batteryId={batteryId} experimentId={experimentId} targetId={targetId ?? "reference_soc_percent"} features={features} mode={mode} target={target} summary={summary} onBuilt={kind => { setBuilt(kind); }} />
      </div>
      {built && <div className="notice mt-4" role="status" data-testid="dataset-handoff">
        <h3>{built === "mlsafe" ? "ML-safe Dataset 请求完成 / ML-safe dataset requested" : "Exploratory Feature Table 请求完成 / Exploratory table requested"}</h3>
        <p className="text-sm mt-1">下一步：在 <Link className="underline" to={`/experiments/${batteryId}/${experimentId}/advanced/splits`}>Advanced → Splits</Link> 建 grouped split（按 cycle 分组），然后到 SOC 建模页训练。</p>
      </div>}
      <div className="mt-5">
        <button className="button" onClick={() => setStep("selection")}>← 上一步</button>
      </div>
    </section>}

    <ScopeNote />
  </>;
}
