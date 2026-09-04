/**
 * BRW-025 typed API client — 契约来自 docs/api/openapi-v1.json。
 *
 * UI 只通过本 client 访问 BRW-024 /api/v1；禁止直接读 parquet/manifest/zarr。
 * client 的路径清单由 tests/client-contract.test.ts 与 OpenAPI snapshot 对齐（drift 检查）。
 */

export const API_BASE = "/api/v1";

export type ApiEnvelope<T> = { data: T; meta?: Record<string, unknown> };

export type ApiErrorCode =
  | "VALIDATION_ERROR"
  | "NOT_FOUND"
  | "CONFLICT"
  | "ARTIFACT_NOT_AVAILABLE"
  | "SCIENTIFIC_ACTION_REQUIRED"
  | "SCIENTIFIC_READINESS_BLOCKED"
  | "INTEGRITY_ERROR"
  | "UNSUPPORTED_OPERATION"
  | "INTERNAL_ERROR";

export interface ApiErrorBody {
  error: {
    code: ApiErrorCode;
    message: string;
    details?: Record<string, unknown>;
    request_id: string;
  };
}

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly requestId: string;
  readonly details: Record<string, unknown>;
  readonly status: number;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.code = body.error.code;
    this.requestId = body.error.request_id;
    this.details = body.error.details ?? {};
    this.status = status;
  }

  get isScientificActionRequired(): boolean {
    return this.code === "SCIENTIFIC_ACTION_REQUIRED";
  }

  get isReadinessBlocked(): boolean {
    return this.code === "SCIENTIFIC_READINESS_BLOCKED";
  }

  get isArtifactUnavailable(): boolean {
    return this.code === "ARTIFACT_NOT_AVAILABLE";
  }
}

// ---------- shared DTO shapes (mirrors openapi-v1.json) ----------

export interface SystemStatus {
  status: string;
}

export interface Capabilities {
  software_capabilities: Record<string, unknown>;
  experiment_readiness: Record<string, string>;
}

export interface ExperimentSummary {
  battery_id: string;
  experiment_id: string;
  experiment_composite_id: string;
  dataset_id: string | null;
  split_id: string | null;
  label_set_id: string | null;
  gate_set_id: string | null;
  feature_set_id: string | null;
  scientific_status: string;
  limitations: string[];
  run_ids: string[];
  latest_canonical_artifacts: Record<string, string>;
}

export interface WorkspaceSummary extends ExperimentSummary {
  limitations_registry: { code: string; severity: string; description: string }[];
  readiness: Record<string, unknown>;
  next_actions: string[];
}

export interface StatusBlock {
  battery_id: string;
  experiment_id: string;
  synchronization: { validated_sync: boolean; timebase_status: string };
  soc: { value: number | null; status: string; reason: string };
  soh: { value: number | null; status: string; reason?: string };
  tof: { value: number | null; status: string; reason: string };
  scientific_status: string;
}

export interface LimitationEntry {
  code: string;
  severity: string;
  description: string;
}

export interface ResultRecord {
  result_id: string;
  result_type: string;
  name: string;
  value: unknown;
  units: string;
  scope: string;
  source_artifact_id: string | null;
  source_run_id: string | null;
  dataset_id: string | null;
  split_id: string | null;
  model_id: string | null;
  model_family: string | null;
  evidence_type: string;
  evidence_ref: string;
  fold_index: number | null;
  strategy: string | null;
  scientific_status: string;
  limitations: string[];
  pooled_rows_usage: string;
}

export interface EvidenceEntry {
  evidence_type: string;
  evidence_ref: string;
  artifact_id: string | null;
  artifact_availability: string;
}

export interface LineageNode {
  artifact_type: string;
  artifact_id: string | null;
  status: string;
}

export interface FeatureInfo {
  feature_name: string;
  role: string | null;
  availability: string;
  gate_id: string | null;
  tof_definition_id: string | null;
  missing_reason: string | null;
}

export interface GateEntry {
  gate_id: string;
  gate_set_id: string;
  gate_name?: string;
  start_sample?: number;
  end_sample?: number;
  waveform_length?: number;
}

export interface RunRecord {
  run_id: string;
  status: string;
  battery_id?: string;
  experiment_id?: string;
  user_actions_pending?: Record<string, unknown>[];
}

export interface RunEvent {
  node: string;
  status: string;
  detail?: Record<string, unknown>;
}

export interface UserActionRequired {
  action_id: string;
  node_id: string;
  action_type: string;
  message: string;
  required_fields: Record<string, unknown>[];
  options: Record<string, unknown>[];
  scientific_reason: string;
  blocking: boolean;
}

export interface ArtifactMetadata {
  artifact_id: string;
  artifact_type: string;
  availability: string;
  status: string;
  row_count: number | null;
  preview: Record<string, unknown>[];
  fields?: Record<string, unknown>;
}

export interface FrameMetadata {
  frame_index: number;
  waveform_group: string;
  waveform_row_index: number;
  sample_count: number;
}

export interface FrameListResponse {
  battery_id: string;
  experiment_id: string;
  frame_count: number;
  waveform_length: number;
  x_axis: string;
  time_axis_available: boolean;
  frames: FrameMetadata[];
}

export interface WaveformSample {
  sample_index: number;
  amplitude_a_u: number;
}

export interface FramePreviewResponse {
  frame_index: number;
  waveform_group: string;
  waveform_row_index: number;
  waveform_length: number;
  x_axis: string;
  time_axis_us: number | null;
  sampling_rate_status: string;
  max_points: number;
  samples: WaveformSample[];
}

// ---------- client ----------

async function request<T>(path: string, init?: RequestInit): Promise<ApiEnvelope<T>> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      ...init,
    });
  } catch (networkError) {
    throw new Error(`无法连接工作台 API（${API_BASE}）: ${String(networkError)}`, {
      cause: networkError,
    });
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (
      body !== null &&
      typeof body === "object" &&
      "error" in (body as Record<string, unknown>)
    ) {
      throw new ApiError(response.status, body as ApiErrorBody);
    }
    throw new ApiError(response.status, {
      error: {
        code: "INTERNAL_ERROR",
        message: `HTTP ${response.status}`,
        request_id: "unknown",
      },
    });
  }
  return body as ApiEnvelope<T>;
}

export const client = {
  // system
  health: () => request<SystemStatus>("/health"),
  capabilities: () => request<Capabilities>("/capabilities"),
  version: () => request<{ version: string; api_version: string }>("/version"),

  // experiments
  listExperiments: (limit = 50, cursor?: string) =>
    request<ExperimentSummary[]>(
      `/experiments?limit=${limit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
    ),
  getExperiment: (batteryId: string, experimentId: string) =>
    request<ExperimentSummary>(`/experiments/${batteryId}/${experimentId}`),
  getStatus: (batteryId: string, experimentId: string) =>
    request<StatusBlock>(`/experiments/${batteryId}/${experimentId}/status`),
  getWorkspaceSummary: (batteryId: string, experimentId: string) =>
    request<WorkspaceSummary>(`/experiments/${batteryId}/${experimentId}/workspace-summary`),
  getResults: (batteryId: string, experimentId: string, limit = 200, resultType?: string) =>
    request<ResultRecord[]>(
      `/experiments/${batteryId}/${experimentId}/results?limit=${limit}${resultType ? `&result_type=${resultType}` : ""}`,
    ),
  getLimitations: (batteryId: string, experimentId: string) =>
    request<{ limitations: LimitationEntry[] }>(
      `/experiments/${batteryId}/${experimentId}/limitations`,
    ),
  getEvidence: (batteryId: string, experimentId: string) =>
    request<{ evidence: EvidenceEntry[] }>(
      `/experiments/${batteryId}/${experimentId}/evidence`,
    ),
  getLineage: (batteryId: string, experimentId: string) =>
    request<{ battery_id: string; experiment_id: string; lineage_chain: LineageNode[] }>(
      `/experiments/${batteryId}/${experimentId}/lineage`,
    ),

  // waveform preview
  listWaveformFrames: (batteryId: string, experimentId: string) =>
    request<FrameListResponse>(`/experiments/${batteryId}/${experimentId}/waveform-frames`),
  getWaveformFrame: (
    batteryId: string,
    experimentId: string,
    frameIndex: number,
    maxPoints = 500,
  ) =>
    request<FramePreviewResponse>(
      `/experiments/${batteryId}/${experimentId}/waveform-frames/${frameIndex}?max_points=${maxPoints}`,
    ),

  // gates
  listGates: (batteryId: string, experimentId: string) =>
    request<{ gates: GateEntry[] }>(`/experiments/${batteryId}/${experimentId}/gates`),
  getGate: (gateId: string) => request<GateEntry>(`/gates/${encodeURIComponent(gateId)}`),
  createGate: (body: {
    battery_id: string;
    experiment_id: string;
    gate_name: string;
    start_sample: number;
    end_sample: number;
    waveform_length: number;
  }) => request<{ gate_id: string; gate_set_id: string; reuse_status: string }>("/gates", {
    method: "POST",
    body: JSON.stringify(body),
  }),

  // features
  listFeatures: (batteryId: string, experimentId: string) =>
    request<{ features: FeatureInfo[] }>(`/experiments/${batteryId}/${experimentId}/features`),

  // feature analysis
  createFeatureAnalysis: (body: {
    battery_id: string;
    experiment_id: string;
    analysis_mode: "EXPLORATORY_FULL_DATA" | "TRAIN_ONLY_ML_SAFE";
    target: string;
    candidate_features: string[];
  }) =>
    request<{ analysis_id: string; analysis_mode: string; reuse_status: string }>(
      "/feature-analyses",
      { method: "POST", body: JSON.stringify(body) },
    ),
  getFeatureAnalysis: (analysisId: string) =>
    request<{ analysis_id: string; status: string }>(
      `/feature-analyses/${encodeURIComponent(analysisId)}`,
    ),

  // datasets / splits / models
  createDataset: (body: {
    battery_id: string;
    experiment_id: string;
    dataset_family?: string;
    target?: string;
    selected_features?: string[];
  }) => request<Record<string, unknown>>("/datasets", { method: "POST", body: JSON.stringify(body) }),
  createSplit: (body: {
    battery_id: string;
    experiment_id: string;
    dataset_id: string;
    strategy?: string;
  }) => request<Record<string, unknown>>("/splits", { method: "POST", body: JSON.stringify(body) }),
  createBaselineModel: (body: {
    battery_id: string;
    experiment_id: string;
    strategy: string;
    dataset_id: string;
    split_id: string;
    fold_index: number;
    selection_id: string;
    selected_features: string[];
  }) =>
    request<{ model_id: string; tuning: boolean; reuse_status: string }>(
      "/models/baseline-runs",
      { method: "POST", body: JSON.stringify(body) },
    ),
  getArtifact: (artifactId: string) =>
    request<ArtifactMetadata>(`/artifacts/${encodeURIComponent(artifactId)}`),

  // reports
  createReport: (body: { battery_id: string; experiment_id: string; target?: string }) =>
    request<Record<string, unknown>>("/reports", { method: "POST", body: JSON.stringify(body) }),
  listReports: (batteryId: string, experimentId: string, limit = 50, cursor?: string) =>
    request<Record<string, unknown>[]>(
      `/reports?battery_id=${batteryId}&experiment_id=${experimentId}&limit=${limit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
    ),
  getReport: (reportId: string) =>
    request<Record<string, unknown>>(`/reports/${encodeURIComponent(reportId)}`),

  // runs
  listRuns: (limit = 50, cursor?: string) =>
    request<{ runs: RunRecord[] }>(`/runs?limit=${limit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`),
  startRun: (body: { profile: string; battery_id: string; experiment_id: string }, idempotencyKey?: string) =>
    request<Record<string, unknown>>("/runs", {
      method: "POST",
      headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
      body: JSON.stringify(body),
    }),
  dryRun: (body: { profile: string; battery_id: string; experiment_id: string }) =>
    request<Record<string, unknown>>("/runs/dry-run", { method: "POST", body: JSON.stringify(body) }),
  getRun: (runId: string) =>
    request<Record<string, unknown>>(`/runs/${encodeURIComponent(runId)}`),
  getRunEvents: (runId: string) =>
    request<{ run_id: string; events: RunEvent[] }>(`/runs/${encodeURIComponent(runId)}/events`),
  resumeRun: (runId: string) =>
    request<Record<string, unknown>>(`/runs/${encodeURIComponent(runId)}/resume`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  retryRun: (runId: string, nodeId: string) =>
    request<Record<string, unknown>>(`/runs/${encodeURIComponent(runId)}/retry`, {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId }),
    }),
  listUserActions: (runId: string) =>
    request<{ run_id: string; user_actions: UserActionRequired[] }>(
      `/runs/${encodeURIComponent(runId)}/user-actions`,
    ),
  submitUserAction: (runId: string, actionId: string, values: Record<string, unknown>) =>
    request<Record<string, unknown>>(
      `/runs/${encodeURIComponent(runId)}/user-actions/${encodeURIComponent(actionId)}`,
      { method: "POST", body: JSON.stringify({ values }) },
    ),
};

/** client 覆盖的 API 路径清单 — drift 测试与 openapi-v1.json 对齐用。 */
export const CLIENT_PATHS: { method: string; path: string }[] = [
  { method: "GET", path: "/health" },
  { method: "GET", path: "/capabilities" },
  { method: "GET", path: "/version" },
  { method: "GET", path: "/experiments" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/status" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/workspace-summary" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/results" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/limitations" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/evidence" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/lineage" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/waveform-frames" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/waveform-frames/{frame_index}" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/gates" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/features" },
  { method: "POST", path: "/experiments/{battery_id}/{experiment_id}/parameters" },
  { method: "GET", path: "/gates/{gate_id}" },
  { method: "POST", path: "/gates" },
  { method: "POST", path: "/feature-analyses" },
  { method: "GET", path: "/feature-analyses/{analysis_id}" },
  { method: "POST", path: "/datasets" },
  { method: "GET", path: "/datasets/{dataset_id}" },
  { method: "POST", path: "/splits" },
  { method: "GET", path: "/splits/{split_id}" },
  { method: "POST", path: "/models/baseline-runs" },
  { method: "POST", path: "/reports" },
  { method: "GET", path: "/reports" },
  { method: "GET", path: "/reports/{report_id}" },
  { method: "GET", path: "/artifacts/{artifact_id}" },
  { method: "GET", path: "/artifacts/{artifact_id}/preview" },
  { method: "GET", path: "/runs" },
  { method: "POST", path: "/runs" },
  { method: "POST", path: "/runs/dry-run" },
  { method: "POST", path: "/runs/plan" },
  { method: "GET", path: "/runs/{run_id}" },
  { method: "GET", path: "/runs/{run_id}/events" },
  { method: "POST", path: "/runs/{run_id}/resume" },
  { method: "POST", path: "/runs/{run_id}/retry" },
  { method: "GET", path: "/runs/{run_id}/user-actions" },
  { method: "POST", path: "/runs/{run_id}/user-actions/{action_id}" },
];
