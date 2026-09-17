/**
 * BRW-025R-WF — ScientificWorkflowContext query hook.
 *
 * Single source of truth for workflow state across all pages.
 * Wraps GET /workflow-context with react-query; keys include batteryId/experimentId
 * so experiment switching automatically isolates cache (§12).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { client, type WorkflowContextPayload, WF_STEP_KEYS, type WfStepKey, type WfStepVisualStatus } from "../api/client";

/** Query key — includes batteryId + experimentId for isolation. */
export function workflowContextKey(batteryId: string, experimentId: string) {
  return ["workflow-context", batteryId, experimentId] as const;
}

/** Fetch workflow context from backend read model. */
export function useWorkflowContext(batteryId: string, experimentId: string) {
  return useQuery({
    queryKey: workflowContextKey(batteryId, experimentId),
    queryFn: async () => {
      const res = await client.getWorkflowContext(batteryId, experimentId);
      return res.data;
    },
    enabled: !!batteryId && !!experimentId,
    staleTime: 30_000,
  });
}

/** Invalidate workflow-context + related queries after mutation. */
export function useInvalidateWorkflow() {
  const qc = useQueryClient();
  return (batteryId: string, experimentId: string) => {
    qc.invalidateQueries({ queryKey: workflowContextKey(batteryId, experimentId) });
    // Also invalidate related surface queries so Overview/Assistant refresh
    qc.invalidateQueries({ queryKey: ["research-overview", batteryId, experimentId] });
    qc.invalidateQueries({ queryKey: ["assistant-session", batteryId, experimentId] });
  };
}

/**
 * Derive stepper visual status from backend step_statuses + current_step.
 *
 * Rules:
 * - current_step → CURRENT (visually, the "active" step)
 * - COMPLETE before current_step → COMPLETE
 * - STALE before current_step → STALE
 * - LIMITED → LIMITED
 * - BLOCKED → BLOCKED
 * - NOT_STARTED with previous step COMPLETE → READY
 * - NOT_STARTED otherwise → NOT_STARTED
 */
export function deriveStepperStatuses(
  currentStep: string,
  stepStatuses: Record<string, string>,
  freshness: Record<string, string>,
): Record<string, WfStepVisualStatus> {
  const result: Record<string, WfStepVisualStatus> = {};
  const stepKeys = [...WF_STEP_KEYS];
  const currentIdx = stepKeys.indexOf(currentStep as WfStepKey);

  for (let i = 0; i < stepKeys.length; i++) {
    const key = stepKeys[i]!;
    const rawStatus = stepStatuses[key] ?? "NOT_STARTED";

    if (key === currentStep) {
      // The current step is always CURRENT visually
      result[key] = "CURRENT";
    } else if (rawStatus === "COMPLETE") {
      // Check if stale
      // Map step → freshness key
      const freshnessKey = stepToFreshnessKey(key);
      const fresh = freshnessKey ? freshness[freshnessKey] : null;
      if (fresh === "STALE" || fresh === "LEGACY" || fresh === "SUPERSEDED") {
        result[key] = "STALE";
      } else {
        result[key] = "COMPLETE";
      }
    } else if (rawStatus === "BLOCKED") {
      result[key] = "BLOCKED";
    } else if (rawStatus === "LIMITED") {
      result[key] = "LIMITED";
    } else if (rawStatus === "NOT_STARTED") {
      // If the previous step is COMPLETE/CURRENT, this step is READY
      if (i > 0) {
        const prevKey = stepKeys[i - 1]!;
        const prevStatus = result[prevKey] ?? stepStatuses[prevKey] ?? "NOT_STARTED";
        if (prevStatus === "COMPLETE" || prevStatus === "CURRENT" || prevStatus === "STALE") {
          result[key] = "READY";
        } else {
          result[key] = "NOT_STARTED";
        }
      } else {
        result[key] = "READY"; // First step is always ready
      }
    } else {
      result[key] = rawStatus as WfStepVisualStatus;
    }
  }
  return result;
}

/** Map step key to artifact_freshness key. */
function stepToFreshnessKey(step: string): string | null {
  switch (step) {
    case "DATASET": return "dataset";
    case "MODELS": return "models";
    case "REPORT": return "report";
    default: return null; // TARGET/ALIGNMENT/FEATURES/PREVIEW/SPLIT don't have freshness
  }
}

/** Step key → page route suffix. */
export const WF_STEP_ROUTES: Record<string, string> = {
  TARGET: "analysis",
  ALIGNMENT: "analysis",
  FEATURES: "analysis",
  PREVIEW: "analysis",
  DATASET: "analysis",
  SPLIT: "advanced/dataset-split",
  MODELS: "models",
  REPORT: "report",
};

/** Get the route for a step within an experiment. */
export function stepRoute(batteryId: string, experimentId: string, step: string): string {
  const page = WF_STEP_ROUTES[step] ?? "overview";
  return `/experiments/${batteryId}/${experimentId}/${page}`;
}
