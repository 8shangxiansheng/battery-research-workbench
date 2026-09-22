/**
 * BRW-025R-WF §9/§26 — Global WAITING banner.
 *
 * Shows pending action (e.g. sampling rate submission) across all pages.
 * Same-run resume: user completes action → workflow-context refetch → banner disappears.
 */
import { Link } from "react-router-dom";
import { AlertCircle, RefreshCw } from "lucide-react";
import type { WorkflowContextPayload } from "../../api/client";
import { Button } from "../ui/button";

export interface WaitingBannerProps {
  pendingAction: WorkflowContextPayload["pending_action"];
}

export function WaitingBanner({ pendingAction }: WaitingBannerProps) {
  if (!pendingAction || pendingAction.status !== "WAITING_FOR_USER") return null;

  return (
    <div
      className="notice !border-amber-300 !bg-amber-50 mb-4 flex items-start gap-3"
      role="alert"
      data-testid="waiting-banner"
    >
      <AlertCircle size={18} className="text-amber-600 mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-amber-800">
          等待输入 / Waiting for your input
        </p>
        <p className="text-sm text-amber-700 mt-1">{pendingAction.label}</p>
        {pendingAction.scientific_reason && (
          <p className="text-xs text-amber-600 mt-1">{pendingAction.scientific_reason}</p>
        )}
        {pendingAction.submissions && pendingAction.submissions.length > 0 && (
          <p className="text-xs text-amber-600 mt-1">
            待恢复提交 / Pending submissions: {pendingAction.submissions.length}
          </p>
        )}
      </div>
      {pendingAction.route && (
        <Button asChild variant="outline" size="sm" className="shrink-0 border-amber-300 text-amber-700 hover:bg-amber-100">
          <Link to={pendingAction.route} data-testid="waiting-banner-action">
            <RefreshCw size={14} className="mr-1" />
            处理 / Resolve
          </Link>
        </Button>
      )}
    </div>
  );
}
