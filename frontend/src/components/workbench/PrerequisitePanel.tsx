/**
 * BRW-025R-WF §6/§11 — Deep-link prerequisite recovery panel.
 *
 * When a user deep-links to a step with BLOCKED/NOT_STARTED status,
 * show the prerequisite state + exact next action (never 404/blank).
 */
import { Link } from "react-router-dom";
import { ArrowRight, Lock } from "lucide-react";
import type { WorkflowContextPayload } from "../../api/client";
import { Button } from "../ui/button";

export interface PrerequisitePanelProps {
  stepKey: string;
  stepStatus: string;
  stepDetail: WorkflowContextPayload["steps"][string];
  recommended: WorkflowContextPayload["recommended_next_action"];
  batteryId: string;
  experimentId: string;
}

export function PrerequisitePanel({ stepKey, stepStatus, stepDetail, recommended }: PrerequisitePanelProps) {
  const blocking = stepDetail?.blocking;
  return (
    <div
      className="panel !p-6 text-center max-w-lg mx-auto mt-12"
      data-testid="prerequisite-panel"
      role="status"
    >
      <Lock size={32} className="mx-auto text-muted mb-4" />
      <h2 className="text-lg font-semibold mb-2">
        前置条件未满足 / Prerequisites not met
      </h2>
      <p className="text-sm text-muted mb-4">
        步骤 <strong>{stepKey}</strong> 当前状态: <strong>{stepStatus}</strong>
      </p>
      {blocking?.blocking_message && (
        <p className="text-sm text-[#9b782e] mb-2">{blocking.blocking_message}</p>
      )}
      {blocking?.scientific_reason && (
        <p className="text-xs text-muted mb-4">{blocking.scientific_reason}</p>
      )}
      {recommended && (
        <Button asChild className="mt-2">
          <Link to={recommended.route} data-testid="prerequisite-next-action">
            {recommended.label}
            <ArrowRight size={16} className="ml-2" />
          </Link>
        </Button>
      )}
    </div>
  );
}
