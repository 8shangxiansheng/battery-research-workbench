/**
 * BRW-025R-WF §7 — Workflow stepper V2 (navigation-only).
 *
 * Nine steps: Overview + 8 canonical workflow steps.
 * Seven visual states: COMPLETE / CURRENT / READY / BLOCKED / STALE / NOT_STARTED / LIMITED.
 * Stepper is navigation-only — clicking never materializes scientific artifacts.
 */
import { useNavigate, useParams } from "react-router-dom";
import { CircleCheck, CircleDashed, CircleDot, CircleX, Clock, AlertTriangle, MinusCircle } from "lucide-react";
import type { WfStepVisualStatus } from "../../api/client";
import { WF_STEP_ROUTES } from "../../hooks/useWorkflowContext";

/** Step display metadata (order = canonical workflow). */
const STEP_META: { key: string; label: string; shortLabel: string }[] = [
  { key: "TARGET", label: "目标 / Target", shortLabel: "目标" },
  { key: "ALIGNMENT", label: "对齐 / Alignment", shortLabel: "对齐" },
  { key: "FEATURES", label: "特征 / Features", shortLabel: "特征" },
  { key: "PREVIEW", label: "预览 / Preview", shortLabel: "预览" },
  { key: "DATASET", label: "数据集 / Dataset", shortLabel: "数据集" },
  { key: "SPLIT", label: "分组划分 / Split", shortLabel: "划分" },
  { key: "MODELS", label: "模型 / Models", shortLabel: "模型" },
  { key: "REPORT", label: "报告 / Report", shortLabel: "报告" },
];

const STATUS_ICONS: Record<WfStepVisualStatus, typeof CircleCheck> = {
  COMPLETE: CircleCheck,
  CURRENT: CircleDot,
  READY: CircleDashed,
  BLOCKED: CircleX,
  STALE: Clock,
  NOT_STARTED: MinusCircle,
  LIMITED: AlertTriangle,
};

const STATUS_COLORS: Record<WfStepVisualStatus, string> = {
  COMPLETE: "text-emerald-600 border-emerald-300 bg-emerald-50",
  CURRENT: "text-[#385c66] border-[#385c63] bg-[#e9f1ef] font-semibold",
  READY: "text-blue-600 border-blue-300 bg-blue-50",
  BLOCKED: "text-red-600 border-red-300 bg-red-50 cursor-not-allowed",
  STALE: "text-amber-600 border-amber-300 bg-amber-50",
  NOT_STARTED: "text-muted border-border",
  LIMITED: "text-orange-600 border-orange-300 bg-orange-50",
};

export interface WorkflowStepperV2Props {
  /** Derived visual statuses for each step. */
  statuses: Record<string, WfStepVisualStatus>;
  /** Currently active page (for highlighting). */
  activePage?: string;
}

export function WorkflowStepperV2({ statuses, activePage }: WorkflowStepperV2Props) {
  const { batteryId = "", experimentId = "" } = useParams();
  const navigate = useNavigate();

  function handleStep(stepKey: string) {
    const status = statuses[stepKey] ?? "NOT_STARTED";
    // Never navigate to BLOCKED/NOT_STARTED steps
    if (status === "BLOCKED" || status === "NOT_STARTED") return;
    const route = WF_STEP_ROUTES[stepKey] ?? "overview";
    navigate(`/experiments/${batteryId}/${experimentId}/${route}`);
  }

  return (
    <ol className="flex flex-wrap gap-2 mb-6" data-testid="workflow-stepper-v2" aria-label="科研工作流">
      {STEP_META.map((s, i) => {
        const status = statuses[s.key] ?? "NOT_STARTED";
        const Icon = STATUS_ICONS[status];
        const color = STATUS_COLORS[status];
        const routePath = WF_STEP_ROUTES[s.key]?.split("?")[0];
        const isActive = activePage === routePath && status === "CURRENT";
        const isClickable = status !== "BLOCKED" && status !== "NOT_STARTED";

        return (
          <li key={s.key}>
            <button
              aria-current={isActive && status === "CURRENT" ? "step" : undefined}
              aria-disabled={!isClickable}
              onClick={() => handleStep(s.key)}
              disabled={!isClickable}
              data-testid={`stepper-${s.key.toLowerCase()}`}
              data-status={status}
              className={`flex gap-1.5 items-center text-xs rounded-full border px-3 py-1.5 transition-colors ${color} ${
                isActive ? "ring-1 ring-[#385c63]" : ""
              } ${!isClickable ? "opacity-60" : "hover:shadow-sm cursor-pointer"}`}
              title={`${s.label}: ${status}`}
            >
              <Icon size={13} />
              <span className="hidden sm:inline">{s.shortLabel}</span>
              <span className="sm:hidden">{i + 1}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
