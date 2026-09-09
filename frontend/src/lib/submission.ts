/**
 * BRW-018R2 — shared sampling-parameter submission service (UI side).
 *
 * One service for Assistant / Overview / Waveform / any caller:
 *  - unit conversion Hz/kHz/MHz → value stored in canonical Hz by the backend
 *  - explicit Saving → Saved / Failed states (no silent no-op)
 *  - partial success (saved but resume failed) exposes Retry Resume
 *  - idempotent via client-generated submission id
 *  - refreshes every affected query key so no F5 is needed
 */
import { useQueryClient } from "@tanstack/react-query";
import { client } from "../api/client";

export type SubmissionPhase = "IDLE" | "SAVING" | "SAVED" | "PARTIAL" | "FAILED";

export interface SubmissionState {
  phase: SubmissionPhase;
  submissionId: string | null;
  parameterSetId: string | null;
  runId: string | null;
  runState: string | null;
  resumeStatus: string | null;
  message: string;
}

export interface SamplingSubmissionInput {
  batteryId: string;
  experimentId: string;
  /** numeric value in any of Hz/kHz/MHz */
  value: number;
  unit: "Hz" | "kHz" | "MHz";
  source: string;
  verified: boolean;
  runId?: string | null;
  actionId?: string | null;
}

function newSubmissionId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return "SUB::" + Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
}

/** Query keys invalidated after a submission state change — ParameterSet,
 *  status, readiness/workspace, runs, TOF, calibration, assistant session. */
const SUBMISSION_QUERY_KEY_NAMES = [
  "parameters",
  "status",
  "workspace-summary",
  "canonical-tof",
  "gate-calibration",
  "runs",
  "physical-features",
  "feature-definitions",
  "assistant-session",
] as const;

function submissionQueryKeys(
  batteryId: string,
  experimentId: string,
): (readonly [string, string, string])[] {
  return SUBMISSION_QUERY_KEY_NAMES.map(
    key => [key, batteryId, experimentId] as const,
  );
}

export function useSamplingSubmission() {
  const qc = useQueryClient();
  async function submit(
    input: SamplingSubmissionInput,
    onState: (s: SubmissionState) => void,
  ): Promise<SubmissionState> {
    const submissionId = newSubmissionId();
    onState({
      phase: "SAVING", submissionId, parameterSetId: null, runId: input.runId ?? null,
      runState: null, resumeStatus: null, message: "正在保存采样频率…",
    });
    try {
      const res = await client.submitSamplingParameter(input.batteryId, input.experimentId, {
        values: {
          "ultrasound.sampling_rate_hz": { value: input.value, unit: input.unit },
        },
        source: input.source,
        verified: input.verified,
        run_id: input.runId ?? undefined,
        action_id: input.actionId ?? undefined,
        submission_id: submissionId,
      });
      const d = res.data;
      const phase: SubmissionPhase =
        d.save_status === "FAILED" ? "FAILED"
        : d.resume_status === "FAILED" ? "PARTIAL"
        : d.resume_status === "RESUMED" ? "SAVED"
        : "SAVED";
      const message =
        phase === "SAVED"
          ? d.run_state
            ? `已保存（${d.parameter_set_id}），运行 ${d.run_id} 已恢复（${d.run_state}）。`
            : `已保存（${d.parameter_set_id}）。没有等待中的运行需要恢复。`
        : phase === "PARTIAL"
          ? `参数已保存（${d.parameter_set_id}），但运行恢复失败：${d.resume_error ?? "未知原因"}。可点击“重试恢复”。`
          : `保存失败：${d.save_error ?? "未知原因"}`;
      const state: SubmissionState = {
        phase,
        submissionId: d.submission_id,
        parameterSetId: d.parameter_set_id,
        runId: d.run_id,
        runState: d.run_state,
        resumeStatus: d.resume_status,
        message,
      };
      for (const key of submissionQueryKeys(input.batteryId, input.experimentId)) {
        void qc.invalidateQueries({ queryKey: key });
      }
      onState(state);
      return state;
    } catch (e) {
      const state: SubmissionState = {
        phase: "FAILED", submissionId, parameterSetId: null, runId: input.runId ?? null,
        runState: null, resumeStatus: null,
        message: `保存失败：${e instanceof Error ? e.message : String(e)}`,
      };
      onState(state);
      return state;
    }
  }

  async function retryResume(
    batteryId: string,
    experimentId: string,
    submissionId: string,
    onState: (s: SubmissionState) => void,
  ): Promise<SubmissionState> {
    onState({
      phase: "SAVING", submissionId, parameterSetId: null, runId: null,
      runState: null, resumeStatus: null, message: "正在重试恢复运行…",
    });
    try {
      const res = await client.retrySubmissionResume(batteryId, experimentId, submissionId);
      const d = res.data;
      const state: SubmissionState = {
        phase: d.resume_status === "RESUMED" ? "SAVED" : "PARTIAL",
        submissionId, parameterSetId: d.parameter_set_id ?? null, runId: d.run_id ?? null,
        runState: d.run_state ?? null, resumeStatus: d.resume_status ?? null,
        message:
          d.resume_status === "RESUMED"
            ? `运行 ${d.run_id} 已恢复（${d.run_state}）。`
            : `恢复仍失败：${d.resume_error ?? "未知原因"}`,
      };
      for (const key of submissionQueryKeys(batteryId, experimentId)) {
        void qc.invalidateQueries({ queryKey: key });
      }
      onState(state);
      return state;
    } catch (e) {
      const state: SubmissionState = {
        phase: "PARTIAL", submissionId, parameterSetId: null, runId: null,
        runState: null, resumeStatus: "FAILED",
        message: `恢复仍失败：${e instanceof Error ? e.message : String(e)}`,
      };
      onState(state);
      return state;
    }
  }

  return { submit, retryResume };
}
