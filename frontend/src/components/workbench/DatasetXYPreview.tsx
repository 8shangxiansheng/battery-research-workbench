import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { client, type FeatureLabelPreviewResponse, type TargetDefinition } from "../../api/client";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../ui/dialog";
import { numberText } from "../../lib/presentation";

/** X/y preview shown BEFORE any dataset build (requirement 19). */
export function DatasetXYPreview({ open, onClose, target, summary, features, mode, onBuild, building, built, buildError }: {
  open: boolean; onClose: () => void;
  target: TargetDefinition | undefined;
  summary: FeatureLabelPreviewResponse["summary"] | null;
  features: string[];
  mode: "EXPLORATORY_FULL_DATA" | "TRAIN_ONLY_ML_SAFE";
  onBuild: () => void; building: boolean; built: boolean; buildError: unknown;
}) {
  const isMlSafe = mode === "TRAIN_ONLY_ML_SAFE";
  return <Dialog open={open} onOpenChange={o => { if (!o) onClose(); }}>
    <DialogContent className="max-w-2xl">
      <DialogHeader>
        <DialogTitle>{isMlSafe ? "Build ML-safe Dataset / 构建模型安全数据集" : "Build Exploratory Feature Table / 构建探索性特征表"}</DialogTitle>
        <DialogDescription>Build 前确认 Predictors (X) 与 Target (y)。你的确认仅授权本次请求。</DialogDescription>
      </DialogHeader>
      <div className="grid md:grid-cols-2 gap-4" data-testid="dataset-xy-preview">
        <div className="feature-card !p-4">
          <h3 className="text-sm font-medium">Predictors (X) / 输入特征</h3>
          <ul className="text-xs mt-2 list-disc pl-4 space-y-0.5" data-testid="xy-predictors">
            {features.map(f => <li key={f}>{f}</li>)}
          </ul>
          <p className="text-xs muted mt-2">超声派生特征（TXT waveform）· 超声派生 / Ultrasound-derived</p>
        </div>
        <div className="feature-card !p-4">
          <h3 className="text-sm font-medium">Target (y) / 目标变量</h3>
          <p className="text-sm mt-2" data-testid="xy-target">{target ? `${target.display_name_en} / ${target.display_name_zh}` : "—"}</p>
          <p className="text-xs muted mt-1" data-testid="xy-target-provenance">{target?.source}</p>
          {target?.target_id === "reference_soc_percent" && <p className="text-xs mt-1">Retrospective reference label / 回顾性参考标签（非 True SOC）</p>}
          {target?.limitation_zh && <p className="text-xs text-[#9b782e] mt-1">{target.limitation_zh}</p>}
        </div>
      </div>
      {summary && <dl className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4 text-sm" data-testid="dataset-eligibility">
        <div><dt className="text-xs muted">Eligible rows / 可分析行</dt><dd className="tabular-nums" data-testid="xy-eligible">{numberText(summary.eligible_rows, 0)}</dd></div>
        <div><dt className="text-xs muted">Excluded rows / 排除行</dt><dd className="tabular-nums" data-testid="xy-excluded">{numberText(summary.excluded_rows, 0)}</dd></div>
        <div><dt className="text-xs muted">Cycles / groups</dt><dd className="tabular-nums">{summary.cycles.join(", ") || "—"}</dd></div>
        <div><dt className="text-xs muted">ML-safe status</dt><dd><Badge variant={isMlSafe ? "secondary" : "outline"} data-testid="xy-mlsafe">{isMlSafe ? "TRAIN_ONLY_ML_SAFE" : "EXPLORATORY"}</Badge></dd></div>
      </dl>}
      <p className="text-xs muted">
        Selection mode: {isMlSafe ? "Grouped split → TRAIN-only analysis → locked features → held-out evaluation" : "EXPLORATORY_FULL_DATA — 不能作为正式评估选择"}
      </p>
      {isMlSafe && features.some(f => f.toLowerCase().includes("movmean")) && (
        <p className="text-xs text-[#9b782e]" role="alert"><TriangleAlert size={12} className="inline mr-1" />
          SOURCE_MOVMEAN5 为 Exploratory only，不会静默进入正式建模。</p>)}
      {buildError ? <p role="alert" className="text-sm">数据集请求失败，请检查前置条件后重试。</p> : null}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>取消</Button>
        <Button onClick={onBuild} disabled={building || built} data-testid="confirm-build-dataset">
          {building ? "构建中…" : built ? "已请求 / Requested" : isMlSafe ? "确认构建 ML-safe Dataset" : "确认构建 Exploratory Table"}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}

export function DatasetBuildButtons({ batteryId, experimentId, targetId, features, mode, target, summary, onBuilt }: {
  batteryId: string; experimentId: string; targetId: string; features: string[];
  mode: "EXPLORATORY_FULL_DATA" | "TRAIN_ONLY_ML_SAFE";
  target: TargetDefinition | undefined;
  summary: FeatureLabelPreviewResponse["summary"] | null;
  onBuilt: (kind: "exploratory" | "mlsafe") => void;
}) {
  return <BuildButtonsInner batteryId={batteryId} experimentId={experimentId} targetId={targetId}
    features={features} mode={mode} target={target} summary={summary} onBuilt={onBuilt} />;
}

function BuildButtonsInner({ batteryId, experimentId, targetId, features, mode, target, summary, onBuilt }: {
  batteryId: string; experimentId: string; targetId: string; features: string[];
  mode: "EXPLORATORY_FULL_DATA" | "TRAIN_ONLY_ML_SAFE";
  target: TargetDefinition | undefined;
  summary: FeatureLabelPreviewResponse["summary"] | null;
  onBuilt: (kind: "exploratory" | "mlsafe") => void;
}) {
  const [open, setOpen] = useState(false);
  const mutation = useMutation({
    mutationFn: () => client.createDataset({
      battery_id: batteryId, experiment_id: experimentId,
      dataset_family: mode === "TRAIN_ONLY_ML_SAFE" ? "SOC" : "SOC",
      target: targetId === "reference_soc_percent" ? "soc_reference_percent" : targetId,
      selected_features: features,
    }),
    onSuccess: () => { setOpen(false); onBuilt(mode === "TRAIN_ONLY_ML_SAFE" ? "mlsafe" : "exploratory"); },
  });
  return <>
    <div className="flex flex-wrap gap-3" data-testid="dataset-build-buttons">
      <Button variant="outline" disabled={!features.length} onClick={() => setOpen(true)} data-testid="build-exploratory-btn">
        Build Exploratory Feature Table / 构建探索性特征表</Button>
      <Button disabled={!features.length} onClick={() => setOpen(true)} data-testid="build-mlsafe-btn">
        Build ML-safe Dataset / 构建模型安全数据集</Button>
    </div>
    <DatasetXYPreview open={open} onClose={() => setOpen(false)} target={target} summary={summary}
      features={features} mode={mode} building={mutation.isPending}
      built={mutation.isSuccess} buildError={mutation.error}
      onBuild={() => mutation.mutate()} />
  </>;
}
