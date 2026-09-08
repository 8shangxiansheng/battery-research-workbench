import { useQuery } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, CircleDashed } from "lucide-react";
import { client, type TargetDefinition } from "../../api/client";
import { Badge } from "../ui/badge";
import { LoadingState, ErrorState } from "./shared";
import { numberText } from "../../lib/presentation";

export const WORKFLOW_STEPS = [
  { key: "target", label: "目标 / Target" },
  { key: "alignment", label: "对齐 / Alignment" },
  { key: "features", label: "特征 / Features" },
  { key: "relationships", label: "关系 / Relationships" },
  { key: "selection", label: "筛选 / Selection" },
  { key: "dataset", label: "数据集 / Dataset" },
] as const;
export type WorkflowStepKey = (typeof WORKFLOW_STEPS)[number]["key"];

export function WorkflowStepper({ current, onStep }: { current: WorkflowStepKey; onStep: (k: WorkflowStepKey) => void }) {
  const idx = WORKFLOW_STEPS.findIndex(s => s.key === current);
  return <ol className="flex flex-wrap gap-2 mb-8" data-testid="workflow-stepper" aria-label="分析工作流">
    {WORKFLOW_STEPS.map((s, i) => <li key={s.key}>
      <button
        aria-current={current === s.key ? "step" : undefined}
        onClick={() => onStep(s.key)}
        className={`flex gap-2 items-center text-sm rounded-full border px-4 py-1.5 transition-colors ${
          current === s.key ? "border-primary bg-[#e9f1ef] font-medium"
          : i < idx ? "border-muted text-muted hover:bg-[#f3f7f6]" : "border-border text-muted"}`}
      >
        <span className="text-xs">{i + 1}</span>{s.label}
      </button>
    </li>)}
  </ol>;
}

function readinessBadge(t: TargetDefinition) {
  if (t.readiness === "READY" || t.readiness === "READY_FOR_LIMITED_EVALUATION")
    return <Badge variant="secondary" data-testid={`target-ready-${t.target_id}`}><CircleCheck size={12} className="mr-1" />可分析 / Usable</Badge>;
  if (t.readiness === "NOT_READY")
    return <Badge variant="outline" data-testid={`target-limited-${t.target_id}`}><CircleAlert size={12} className="mr-1" />Limited / 受限</Badge>;
  return <Badge variant="outline" data-testid={`target-unavailable-${t.target_id}`}><CircleDashed size={12} className="mr-1" />Unavailable / 不可用</Badge>;
}

export function TargetSelector({ batteryId, experimentId, selected, onSelect }: {
  batteryId: string; experimentId: string; selected: string | null; onSelect: (targetId: string) => void;
}) {
  const targets = useQuery({
    queryKey: ["targets", batteryId, experimentId],
    queryFn: () => client.listTargets(batteryId, experimentId),
  });
  if (targets.isLoading) return <LoadingState />;
  if (targets.error) return <ErrorState error={targets.error} retry={() => void targets.refetch()} />;
  const list = targets.data?.data.targets ?? [];
  return <div data-testid="target-selector">
    <h2 className="text-xl">What do you want to study? / 你想研究什么？</h2>
    <p className="muted text-sm mt-1">目标来自后端能力报告；每个目标显示来源、覆盖与限制。</p>
    <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4 mt-4">
      {list.map(t => <label key={t.target_id} data-testid={`target-card-${t.target_id}`}
        className={`feature-card cursor-pointer ${selected === t.target_id ? "!border-primary !bg-[#f0f6f4]" : ""}`}>
        <div className="flex items-start gap-3">
          <input type="radio" name="study-target" className="mt-1 accent-[#385c66]"
            checked={selected === t.target_id} onChange={() => onSelect(t.target_id)}
            aria-label={`Select ${t.display_name_en}`} data-testid={`select-target-${t.target_id}`} />
          <div className="flex-1 min-w-0">
            <h3 className="font-medium">{t.display_name_en} / {t.display_name_zh}</h3>
            <p className="text-xs muted mt-1">{t.semantic_type.replace(/_/g, " ").toLowerCase()} · {t.unit}</p>
            {readinessBadge(t)}
            <dl className="text-xs mt-3 space-y-1">
              <div><dt className="inline muted">Source / 来源: </dt><dd className="inline">{t.source}</dd></div>
              <div><dt className="inline muted">Coverage / 覆盖: </dt><dd className="inline tabular-nums">{numberText(t.coverage.valid, 0)} / {numberText(t.coverage.total, 0)} 行{t.coverage.independent_states != null ? ` · ${t.coverage.independent_states} 独立状态` : ""}</dd></div>
              {t.range && <div><dt className="inline muted">Range / 范围: </dt><dd className="inline tabular-nums">{numberText(t.range[0], 2)} – {numberText(t.range[1], 2)} {t.unit}</dd></div>}
              {t.limitation && <div className="text-warning, text-[#9b782e]"><dt className="inline">Limitation / 限制: </dt><dd className="inline">{t.limitation_zh ?? t.limitation}</dd></div>}
            </dl>
            {t.target_id === "reference_soc_percent" && <p className="text-xs mt-2 text-[#5c7078]" data-testid="soc-retrospective-note">
              Retrospective segment-normalized reference label / 回顾性分段归一化参考标签</p>}
          </div>
        </div>
      </label>)}
    </div>
    <p className="text-xs muted mt-3">目标值由后端 label engine 与 canonical artifacts 提供；前端不计算 SOC/SOH。</p>
  </div>;
}
