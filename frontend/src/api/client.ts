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
  status?: string;
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


// ---------- BRW-024R intake DTOs ----------

export type IntakeSessionStatus =
  | "DRAFT" | "ASSETS_RECEIVED" | "DETECTED" | "VALIDATED"
  | "COMMITTED" | "FAILED" | "CANCELLED" | "EXPIRED";

export type ExperimentLifecycle =
  | "DRAFT" | "AWAITING_DATA" | "IMPORTING" | "IMPORT_VALIDATION_REQUIRED"
  | "READY_FOR_PIPELINE" | "WAITING_FOR_USER" | "RUNNING" | "READY"
  | "FAILED" | "ARCHIVED";

export type AssetRole = "ELECTRICAL" | "ULTRASOUND" | "EXPERIMENT_METADATA" | "AUXILIARY";

export interface LibraryExperiment {
  battery_id: string;
  experiment_id: string;
  experiment_composite_id: string;
  name: string;
  status: ExperimentLifecycle | string;
  is_demo: boolean;
  created_at: string;
  updated_at: string;
  notes: string;
  asset_summary: { committed_assets: number; intake_sessions: number };
  latest_run: string | null;
  readiness: unknown;
  pending_actions: unknown[];
}

export interface IntakeAssetRecord {
  intake_asset_id: string;
  session_id: string;
  role: AssetRole;
  original_filename: string;
  stored_filename: string;
  size: number;
  sha256: string;
  received_at: string;
  content_kind: string | null;
}

export interface AdapterDetection {
  intake_asset_id: string;
  state: "DETECTED_UNIQUE" | "DETECTED_AMBIGUOUS" | "UNSUPPORTED" | "NEEDS_USER_CONFIRMATION";
  modality: string | null;
  adapter_id: string | null;
  adapter_version: string | null;
  asset_role: AssetRole | null;
  detection_reason: string;
  matched_signatures: string[];
  candidates: { modality: string; adapter_id: string; adapter_version: string }[];
}

export interface ValidationCheck {
  dimension: "FORMAT_VALIDITY" | "SCIENTIFIC_METADATA_COMPLETENESS" | "PIPELINE_READINESS";
  level: string;
  passed: boolean;
  detail: string;
}

export interface ImportValidation {
  session_id: string;
  validation_level: string;
  overall_passed: boolean;
  checks: ValidationCheck[];
  sampling_rate_hz: number | null;
  sampling_rate_status: "UNKNOWN" | "RESOLVED";
  timebase_status: string;
}

export interface IntakeSessionDetail {
  session_id: string;
  battery_id: string;
  experiment_id: string;
  experiment_composite_id: string;
  status: IntakeSessionStatus;
  created_at: string;
  updated_at: string;
  assets: IntakeAssetRecord[];
  detections: AdapterDetection[];
  validation: ImportValidation | null;
  commit: {
    session_id: string;
    committed_at: string;
    experiment_composite_id: string;
    assets: Record<string, unknown>[];
    import_manifest_checksum: string;
  } | null;
  failure_reason: string | null;
  recommended_next_action: string | null;
}

export interface IntakeCapabilities {
  adapters: { modality: string; adapter_id: string; adapter_version: string }[];
  supported_roles: AssetRole[];
  file_limits: { max_file_size_bytes: number; max_assets_per_session: number };
  format_hints: Record<string, string>;
  extension_note: string;
  intake_policy_version: string;
}

// ---------- BRW-025R data DTOs ----------

export interface DataQuality {
  battery_id: string;
  experiment_id: string;
  electrical: { records: number; cycles: number | null; steps: number | null; duplicate_timestamps: number | null } | null;
  ultrasound: { frames: number; frame_cadence_s: number | null; sampling_rate_hz: null; sampling_rate_status: "UNKNOWN"; note: string } | null;
}

export interface SynchronizationSummary {
  battery_id: string;
  experiment_id: string;
  matches_frames: number | null;
  match_state: "MATCHED_UNIQUE" | "AMBIGUOUS";
  ambiguous_frames: unknown[];
  sync_tolerance_s: number | null;
  validated_sync: boolean;
  timebase_status: string;
  note: string;
}

export interface MeasurementEventRow {
  measurement_event_id: string;
  frame_index_raw: number | null;
  timestamp: string | null;
  cycle_index_raw: number | null;
  step_index_raw: number | null;
  voltage_v: number | null;
  current_a: number | null;
  soc_reference_percent: number | null;
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
  // ---------- BRW-024R intake ----------
  intakeCapabilities: () =>
    request<IntakeCapabilities>("/intake/capabilities"),
  createExperiment: (body: {
    battery_id: string;
    experiment_id?: string;
    name: string;
    is_demo?: boolean;
    notes?: string;
  }) => request<LibraryExperiment>("/experiments", { method: "POST", body: JSON.stringify(body) }),
  listLibraryExperiments: (params?: { limit?: number; cursor?: string; status?: string; battery_id?: string; is_demo?: boolean }) => {
    const q = new URLSearchParams();
    if (params?.limit) q.set("limit", String(params.limit));
    if (params?.cursor) q.set("cursor", params.cursor);
    if (params?.status) q.set("status", params.status);
    if (params?.battery_id) q.set("battery_id", params.battery_id);
    if (params?.is_demo !== undefined) q.set("is_demo", String(params.is_demo));
    return request<{ experiments: LibraryExperiment[] }>(`/experiments?${q}`);
  },
  patchExperiment: (batteryId: string, experimentId: string, body: { name?: string; notes?: string }) =>
    request<LibraryExperiment>(`/experiments/${batteryId}/${experimentId}`, {
      method: "PATCH", body: JSON.stringify(body),
    }),
  archiveExperiment: (batteryId: string, experimentId: string) =>
    request<LibraryExperiment>(`/experiments/${batteryId}/${experimentId}/archive`, { method: "POST", body: JSON.stringify({}) }),
  loadDemo: (batteryId: string, experimentId: string) =>
    request<LibraryExperiment>(`/experiments/${batteryId}/${experimentId}/load-demo`, { method: "POST", body: JSON.stringify({}) }),
  createIntakeSession: (batteryId: string, experimentId: string) =>
    request<IntakeSessionDetail>(`/experiments/${batteryId}/${experimentId}/intake-sessions`, { method: "POST", body: JSON.stringify({}) }),
  getIntakeSession: (sessionId: string) =>
    request<IntakeSessionDetail>(`/intake-sessions/${encodeURIComponent(sessionId)}`),
  uploadIntakeAsset: (sessionId: string, role: AssetRole, file: File) => {
    const form = new FormData();
    form.append("role", role);
    form.append("file", file);
    return request<IntakeAssetRecord>(`/intake-sessions/${encodeURIComponent(sessionId)}/assets`, {
      method: "POST",
      body: form,
    });
  },
  listIntakeAssets: (sessionId: string) =>
    request<{ assets: IntakeAssetRecord[] }>(`/intake-sessions/${encodeURIComponent(sessionId)}/assets`),
  getIntakeAssetPreview: (sessionId: string, intakeAssetId: string) =>
    request<Record<string, unknown>>(
      `/intake-sessions/${encodeURIComponent(sessionId)}/assets/${encodeURIComponent(intakeAssetId)}/preview`,
    ),
  detectIntakeSession: (sessionId: string) =>
    request<{ detections: AdapterDetection[] }>(`/intake-sessions/${encodeURIComponent(sessionId)}/detect`, { method: "POST", body: JSON.stringify({}) }),
  validateIntakeSession: (sessionId: string) =>
    request<ImportValidation & { next_action?: string }>(`/intake-sessions/${encodeURIComponent(sessionId)}/validate`, { method: "POST", body: JSON.stringify({}) }),
  commitIntakeSession: (sessionId: string) =>
    request<Record<string, unknown>>(`/intake-sessions/${encodeURIComponent(sessionId)}/commit`, { method: "POST", body: JSON.stringify({}) }),
  cancelIntakeSession: (sessionId: string) =>
    request<IntakeSessionDetail>(`/intake-sessions/${encodeURIComponent(sessionId)}/cancel`, { method: "POST", body: JSON.stringify({}) }),
  listExperimentAssets: (batteryId: string, experimentId: string) =>
    request<{ assets: Record<string, unknown>[] }>(`/experiments/${batteryId}/${experimentId}/assets`),
  getIntakeHistory: (batteryId: string, experimentId: string) =>
    request<{ history: Record<string, unknown>[] }>(`/experiments/${batteryId}/${experimentId}/intake-history`),

  // ---------- BRW-025R data workspace ----------
  getDataQuality: (batteryId: string, experimentId: string) =>
    request<DataQuality>(`/experiments/${batteryId}/${experimentId}/data-quality`),
  getSynchronization: (batteryId: string, experimentId: string) =>
    request<SynchronizationSummary>(`/experiments/${batteryId}/${experimentId}/synchronization`),
  getMeasurementEvents: (batteryId: string, experimentId: string, limit = 50, cursor?: number) =>
    request<{ total: number; events: MeasurementEventRow[] }>(
      `/experiments/${batteryId}/${experimentId}/measurement-events?limit=${limit}${cursor !== undefined ? `&cursor=${cursor}` : ""}`,
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
  { method: "GET", path: "/intake/capabilities" },
  { method: "POST", path: "/experiments" },
  { method: "PATCH", path: "/experiments/{battery_id}/{experiment_id}" },
  { method: "POST", path: "/experiments/{battery_id}/{experiment_id}/archive" },
  { method: "POST", path: "/experiments/{battery_id}/{experiment_id}/load-demo" },
  { method: "POST", path: "/experiments/{battery_id}/{experiment_id}/intake-sessions" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/intake-history" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/lifecycle-events" },
  { method: "GET", path: "/intake-sessions/{session_id}" },
  { method: "POST", path: "/intake-sessions/{session_id}/assets" },
  { method: "GET", path: "/intake-sessions/{session_id}/assets" },
  { method: "GET", path: "/intake-sessions/{session_id}/assets/{intake_asset_id}/preview" },
  { method: "POST", path: "/intake-sessions/{session_id}/detect" },
  { method: "POST", path: "/intake-sessions/{session_id}/validate" },
  { method: "POST", path: "/intake-sessions/{session_id}/commit" },
  { method: "POST", path: "/intake-sessions/{session_id}/cancel" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/data-quality" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/synchronization" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/measurement-events" },
];

/** BRW-024R/025R v2 client 方法（插入到 client 对象内）。 */
