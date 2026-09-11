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
  tof: {
    value: number | null;
    status: string;
    reason: string;
    /** BRW-018R2 live readiness ladder fields */
    sampling_rate_hz?: number | null;
    sampling_rate_verified?: boolean;
    gate_calibration_id?: string;
    gate_calibration_source?: string;
  };
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
  step_type?: string | null;
  temperature_c?: number | null;
}

// ---------- BRW-025R-FE scientific feature workbench DTOs ----------

export interface FeatureDefinitionEntry {
  code: string;
  display_name_en: string;
  display_name_zh: string;
  family: "TD" | "FD";
  units: string;
  formula_source_id: string;
  formula_policy_version: string;
  formula_text: string;
  definition_status: "DEFINED_NOT_VALIDATED" | "DEFINED_AND_VALIDATED";
  parity_status: string;
  existing_alias: string | null;
  scope: string[];
}

export interface PhysicalFeatureBlock {
  feature_code: "BOTTOM_AMP" | "SWA" | "TOF_XCORR" | "ATTENUATION" | "BPS";
  method: string;
  gate_template_id: string | string[];
  display_name_en: string;
  display_name_zh: string;
  unit: string;
  values: (number | null)[];
  physical_time_blocked?: string;
  reference_frame_index?: number;
  blocked_features?: { code: string; status: string }[];
}

export interface CorrelationResultEntry {
  analysis_id: string;
  feature_code: string;
  gate_id: string | null;
  feature_variant: string;
  state_variable: string;
  scope: string;
  method: string;
  coefficient: number | null;
  n_valid: number;
  missing_feature_count: number;
  missing_state_count: number;
  excluded_ineligible_count: number;
  limitations: string[];
  status: string;
}

export interface FeatureCorrelationsResponse {
  feature_code: string;
  n_events: number;
  soc: CorrelationResultEntry[];
  temperature: CorrelationResultEntry;
  soh: CorrelationResultEntry;
  soh_cycle_summary: {
    cycle: number;
    soh_percent: number | null;
    feature_median: number | null;
    feature_mean: number | null;
    feature_std: number | null;
    n_frames: number;
  }[];
}

export interface GateTemplateEntry {
  gate_template_id: string;
  role_en: string;
  role_zh: string;
  matlab_start: number;
  matlab_end: number;
  python_start: number;
  python_end_exclusive: number;
  length_samples: number;
}

export interface CalibrationFrameSample {
  sample_index: number;
  amplitude_a_u: number;
  envelope_a_u: number;
}

export interface GateCalibrationResponse {
  calibration_frame_ids: number[];
  frames: { frame_index: number; samples: CalibrationFrameSample[] }[];
  gate_templates: GateTemplateEntry[];
  diagnostics: {
    frame_index: number;
    peak_sample_in_gate: number;
    peak_containment_fraction: number;
    edge_hit: boolean;
  }[];
  recommendation: string;
  /** BRW-018R2 */
  tof_calibration?: TofCalibrationProvenance;
  tof_gate_diagnostics?: Record<"surface" | "bottom", TofGateDiagnostics>;
}

export interface TofCalibrationProvenance {
  gate_calibration_id: string;
  source: "EXPERIMENT_CONFIRMED" | "SOURCE_TEMPLATE";
  surface_gate_id: string;
  surface_start: number;
  surface_end_exclusive: number;
  bottom_gate_id: string;
  bottom_start: number;
  bottom_end_exclusive: number;
  version: number;
  fallback_identity?: string;
}

export interface TofGateDiagnostics {
  gate_start: number;
  gate_end_exclusive: number;
  peak_global_indices: number[];
  peak_local_indices: number[];
  peak_amplitudes_a_u: number[];
  peak_containment_fractions: number[];
  edge_hit_count: number;
  spread_samples: number;
}

export interface TofGateFreezeResult {
  gate_calibration_id: string;
  version: number;
  reuse_status: "REUSED" | "CREATED";
  prior_gate_calibration_id: string | null;
  surface_diagnostics: TofGateDiagnostics;
  bottom_diagnostics: TofGateDiagnostics;
}

/** BRW-017R2 canonical envelope-peak TOF */
export interface CanonicalTofRow {
  measurement_event_id: string;
  frame_index_raw: number;
  tof_method_id: string;
  tof_definition_version: string;
  surface_gate_id: string;
  bottom_gate_id: string;
  gate_calibration_id: string;
  surface_peak_sample_index: number | null;
  bottom_peak_sample_index: number | null;
  surface_peak_local_index: number | null;
  bottom_peak_local_index: number | null;
  tof_samples: number | null;
  sampling_rate_hz: number | null;
  tof_us: number | null;
  tof_status: string;
  tof_quality_reason: string;
  parameter_set_id: string | null;
}

/** BRW-018R2 sampling-parameter submission result */
export interface SamplingSubmissionResult {
  submission_id: string;
  parameter_set_id: string | null;
  save_status: "SAVED" | "FAILED";
  save_error: string | null;
  fs_value: number | null;
  fs_unit: string | null;
  source: string | null;
  verification_status?: string;
  run_id: string | null;
  pending_action_resolved: boolean;
  resume_status: "RESUMED" | "FAILED" | "NOT_ATTEMPTED";
  resume_error: string | null;
  run_state: string | null;
  replayed?: boolean;
}

export interface CanonicalTofPayload {
  tof_method_id: string;    sampling_rate_hz: number | null;
    sampling_rate_verified: boolean;
    parameter_set_id: string | null;
    surface_gate_id: string;
    bottom_gate_id: string;
    rows: CanonicalTofRow[];
    audit: {
      total_frames: number;
      status_counts: Record<string, number>;
      surface_valid: number;
      bottom_valid: number;
      canonical_tof_valid: number;
      tof_samples_stats: { min: number; median: number; max: number } | null;
      tof_us_stats: { min: number; median: number; max: number } | null;
    };
}

export interface GateCalibrationRecordEntry {
  gate_calibration_id: string;
  gate_template_id: string;
  battery_id: string;
  experiment_id: string;
  source_formula_id: string;
  calibration_frame_ids: number[];
  calibration_basis: string;
  confirmed_by: string;
  status: string;
  version: number;
  confirmed_at: string | null;
  reuse_status: string;
}

// ---------- BRW-025R-FE-R1 target-first workflow DTOs ----------

export interface TargetDefinition {
  target_id: string;
  display_name_en: string;
  display_name_zh: string;
  semantic_type: "DIRECT_MEASUREMENT" | "DERIVED_REFERENCE_LABEL" | "DERIVED_HEALTH_STATE";
  source: string;
  source_detail?: Record<string, number>;
  coverage: { valid: number; total: number; independent_states?: number };
  range: [number, number] | null;
  readiness: string;
  limitation: string | null;
  limitation_zh?: string | null;
  unit: string;
}

export interface AlignmentSummaryResponse {
  total_frames: number;
  matched_unique: number;
  ambiguous: number;
  unmatched: number;
  target_valid: Record<string, number>;
  eligible: number;
  excluded: number;
  sync_quality: {
    validated_sync: boolean;
    timebase_status: string;
    matching_performed: boolean;
    max_sync_error_s: number | null;
    sync_tolerance_s: number | null;
    max_sync_error_limit_s: number | null;
  };
}

export interface AlignmentSampleRow {
  measurement_event_id: string;
  frame_index_raw: number | null;
  ultrasound_timestamp: string | null;
  electrical_asset_id: string | null;
  electrical_record_locator: string | null;
  electrical_timestamp: string | null;
  match_status: string;
  sync_ambiguous: boolean;
  sync_error_s: number | null;
  within_tolerance: boolean | null;
  analysis_eligible: boolean;
  targets: Record<string, number | null>;
}

export interface AlignmentExclusionsResponse {
  exclusions: { reason: string; count: number; measurement_event_ids: string[] }[];
}

export interface FeatureLabelPreviewRow {
  measurement_event_id: string;
  frame_index_raw: number | null;
  cycle: number | null;
  state: string;
  target: number | null;
  values: Record<string, number>;
  sync_error_s: number | null;
  electrical_asset_id: string | null;
  /** BRW-025R-FE-R2 row provenance + split awareness */
  electrical_record_locator?: string | null;
  electrical_row_index?: number | null;
  electrical_timestamp?: string | null;
  match_status?: string | null;
  y_redacted?: boolean;
  split_role?: string;
  fold?: string | null;
}

export interface FeatureMetaEntry {
  label_en: string;
  label_zh: string;
  units: string;
  definition_status: string;
  parity_status: string;
  source: string;
  resolved_name?: string;
  canonical_note?: string;
}

export interface TofProvenance {
  canonical_method: string;
  tof_definition_version: string;
  fs_hz: number | null;
  fs_verified: boolean;
  fs_parameter_set_id: string | null;
  gate_calibration_id: string;
  gate_calibration_source: string;
  gate_calibration_version: number;
  surface_gate_id: string;
  bottom_gate_id: string;
  note: string;
}

export interface AmbiguousPreviewRow {
  measurement_event_id: string;
  frame_index_raw: number | null;
  state: string;
  electrical_identity: null;
  target: null;
  candidate_count: number | null;
  values: Record<string, number>;
  note: string;
}

export interface MaterializedDatasetInfo {
  dataset_id: string;
  materialization_status: string;
  stale_tof: boolean;
  refresh_required: boolean;
  stale_note: string;
  feature_definition_version: string | null;
}

export interface RedactionSummary {
  split_id: string;
  fold: string;
  train_rows: number;
  held_out_rows: number;
  policy: string;
}

export interface FeatureLabelPreviewResponse {
  target_id: string;
  target_source: string | null;
  target_readiness: string | null;
  features: string[];
  rows: FeatureLabelPreviewRow[];
  summary: {
    total_frames: number;
    aligned_events: number;
    eligible_rows: number;
    excluded_rows: number;
    excluded_by_reason: Record<string, number>;
    cycles: number[];
    missing_values: number;
    alignment_status: string;
  };
  /** BRW-025R-FE-R2 preview hardening */
  feature_meta?: Record<string, FeatureMetaEntry>;
  ambiguous_rows?: AmbiguousPreviewRow[];
  tof_provenance?: TofProvenance;
  preview_state?: "PREVIEW_DRAFT";
  spec_hash?: string;
  materialized_dataset?: MaterializedDatasetInfo | null;
  redaction_summary?: RedactionSummary | null;
  grain?: string;
}

export interface FeatureRankingEntry {
  feature_code: string;
  pearson_overall?: number | null;
  spearman_overall?: number | null;
  pearson_charge?: number | null;
  pearson_discharge?: number | null;
  n_valid?: number;
  status?: string;
  direction_dependent?: boolean;
  pearson?: number | null;
  spearman?: number | null;
  state_variable?: string;
}

export interface FeatureRankingResponse {
  mode: string;
  target_id: string;
  ranking: FeatureRankingEntry[];
  group_summary?: {
    cycle: number; soh_percent: number | null; feature_median: number | null;
    feature_mean: number | null; feature_std: number | null; n_frames: number;
  }[];
}

// ---------- BRW-027R research assistant DTOs ----------

export interface AssistantNextAction {
  action_id: string;
  label_en: string;
  label_zh: string;
  intent: string | null;
  confirmation_required: boolean;
}

export interface AssistantSessionTurn {
  turn_id: string;
  role: "user" | "assistant";
  intent: string | null;
  message: string;
  tool_name: string | null;
  tool_status: string | null;
  evidence_refs: string[];
  timestamp: string;
}

export interface AssistantSession {
  session_id: string;
  battery_id: string;
  experiment_id: string;
  current_page: string;
  selected_target: string | null;
  target_readiness: string | null;
  alignment_status: Record<string, unknown> | null;
  selected_features: string[];
  feature_selection_mode: string;
  dataset_id: string | null;
  split_id: string | null;
  model_run_id: string | null;
  report_id: string | null;
  phase: string;
  pending_user_action: Record<string, unknown> | null;
  scientific_limitations: Record<string, unknown>[];
  evidence_refs: string[];
  next_actions: AssistantNextAction[];
  conversation: AssistantSessionTurn[];
}

export interface AssistantMessageResponse {
  message: string;
  intent: string;
  phase: string;
  status: string;
  pending_user_action: Record<string, unknown> | null;
  confirmation_id: string | null;
  evidence_refs: string[];
  limitations: string[];
  next_actions: AssistantNextAction[];
  session: AssistantSession;
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
  listParameters: (batteryId: string, experimentId: string) =>
    request<{ parameter_set_id: string; effective: Record<string, unknown> }[]>(`/experiments/${batteryId}/${experimentId}/parameters`),
  createParameters: (batteryId: string, experimentId: string, body: { values: Record<string, { value: number; unit: string }>; source: string; verified: boolean }) =>
    request<{ parameter_set_id: string; sampling_rate_status: string; status: string }>(`/experiments/${batteryId}/${experimentId}/parameters`, { method: "POST", body: JSON.stringify(body) }),
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
    split_id?: string;
    fold_index?: number;
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

  // ---------- BRW-025R-FE feature workbench ----------
  listFeatureDefinitions: () =>
    request<{
      catalogue: FeatureDefinitionEntry[];
      formula_source_id: string;
      formula_policy_version: string;
    }>("/feature-definitions"),
  listPhysicalFeatures: (batteryId: string, experimentId: string, limit = 200) =>
    request<{
      battery_id: string;
      experiment_id: string;
      frame_count: number;
      features: PhysicalFeatureBlock[];
    }>(`/experiments/${batteryId}/${experimentId}/physical-features?limit=${limit}`),
  getFeatureCorrelations: (batteryId: string, experimentId: string, featureCode: string, limit = 4000) =>
    request<FeatureCorrelationsResponse>(
      `/experiments/${batteryId}/${experimentId}/feature-correlations?feature_code=${encodeURIComponent(featureCode)}&limit=${limit}`,
    ),
  getGateCalibration: (batteryId: string, experimentId: string, nFrames = 32) =>
    request<GateCalibrationResponse>(
      `/experiments/${batteryId}/${experimentId}/gate-calibration?n_frames=${nFrames}`,
    ),
  freezeTofGateCalibration: (batteryId: string, experimentId: string, body: {
    surface: { start: number; end: number };
    bottom: { start: number; end: number };
    confirmed_by?: string;
    calibration_basis?: string;
    surface_gate_id?: string;
    bottom_gate_id?: string;
    notes?: string;
  }) =>
    request<TofGateFreezeResult>(
      `/experiments/${batteryId}/${experimentId}/tof-gate-calibration`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  // ---------- BRW-025R-OV research overview (aggregate read) ----------
  getResearchOverview: (batteryId: string, experimentId: string) =>
    request<ResearchOverviewPayload>(
      `/experiments/${batteryId}/${experimentId}/research-overview`,
    ),
  // ---------- BRW-017R2 canonical envelope-peak TOF ----------
  getCanonicalTof: (batteryId: string, experimentId: string, limit = 200) =>
    request<CanonicalTofPayload>(
      `/experiments/${batteryId}/${experimentId}/canonical-tof?limit=${limit}`,
    ),
  // ---------- BRW-018R2 sampling-parameter submission ----------
  submitSamplingParameter: (
    batteryId: string,
    experimentId: string,
    body: {
      values: Record<string, { value: number; unit: string }>;
      source: string;
      verified: boolean;
      run_id?: string;
      action_id?: string;
      submission_id?: string;
    },
  ) =>
    request<SamplingSubmissionResult>(
      `/experiments/${batteryId}/${experimentId}/sampling-parameter-submission`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  retrySubmissionResume: (batteryId: string, experimentId: string, submissionId: string) =>
    request<SamplingSubmissionResult>(
      `/experiments/${batteryId}/${experimentId}/sampling-parameter-submission/${encodeURIComponent(submissionId)}/retry-resume`,
      { method: "POST" },
    ),
  listTargets: (batteryId: string, experimentId: string) =>
    request<{ targets: TargetDefinition[] }>(`/experiments/${batteryId}/${experimentId}/targets`),
  getAlignmentSummary: (batteryId: string, experimentId: string) =>
    request<AlignmentSummaryResponse>(`/experiments/${batteryId}/${experimentId}/alignment-summary`),
  getAlignmentSamples: (batteryId: string, experimentId: string, filter: "eligible" | "ambiguous" | "unmatched" | "all", limit = 20, cursor = 0) =>
    request<{ samples: AlignmentSampleRow[]; total: number }>(
      `/experiments/${batteryId}/${experimentId}/alignment-samples?filter=${filter}&limit=${limit}&cursor=${cursor}`,
    ),
  getAlignmentExclusions: (batteryId: string, experimentId: string) =>
    request<AlignmentExclusionsResponse>(`/experiments/${batteryId}/${experimentId}/alignment-exclusions`),
  postFeatureLabelPreview: (batteryId: string, experimentId: string, body: { target_id: string; features: string[]; limit?: number; split_id?: string; fold_index?: string }) =>
    request<FeatureLabelPreviewResponse>(`/experiments/${batteryId}/${experimentId}/feature-label-preview`, {
      method: "POST", body: JSON.stringify(body),
    }),
  postFeatureTargetRanking: (batteryId: string, experimentId: string, body: { target_id: string; features: string[]; mode: string }) =>
    request<FeatureRankingResponse>(`/experiments/${batteryId}/${experimentId}/feature-target-ranking`, {
      method: "POST", body: JSON.stringify(body),
    }),
  openAssistantSession: (batteryId: string, experimentId: string) =>
    request<AssistantSession>(`/experiments/${batteryId}/${experimentId}/assistant/session`, { method: "POST" }),
  sendAssistantMessage: (batteryId: string, experimentId: string, sessionId: string, message: string, currentPage: string) =>
    request<AssistantMessageResponse>(
      `/experiments/${batteryId}/${experimentId}/assistant/session/${encodeURIComponent(sessionId)}/message`,
      { method: "POST", body: JSON.stringify({ message, current_page: currentPage }) },
    ),
  listMaterializedAnalyses: (batteryId: string, experimentId: string) =>
    request<{ analyses: { analysis_id: string; analysis_mode: string; target: string; split_id: string | null; fold_index: number | null; dataset_id: string | null; candidate_features: string[]; selected_features: string[]; selection_basis: string | null; status: string }[] }>(
      `/experiments/${batteryId}/${experimentId}/feature-analyses`,
    ),
  listSplits: (batteryId: string, experimentId: string) =>
    request<{ splits: { split_id: string; dataset_id: string | null; strategy: string | null; readiness_status: string | null }[] }>(
      `/experiments/${batteryId}/${experimentId}/splits`,
    ),
  freezeGateCalibration: (batteryId: string, experimentId: string, body: {
    confirmed_by: string;
    calibration_basis: string;
  }) =>
    request<GateCalibrationRecordEntry>(
      `/experiments/${batteryId}/${experimentId}/gate-calibration`,
      { method: "POST", body: JSON.stringify(body) },
    ),
};

/** BRW-025R-OV research overview aggregate payload */
export interface ResearchMetadataEntry {
  status: string;
  value?: unknown;
  hz?: number | null;
  verified?: boolean;
  parameter_set_id?: string | null;
  channel?: string[] | null;
  range_c?: [number, number];
  start?: string | null;
  end?: string | null;
}

export interface ResearchOverviewPayload {
  schema_version: string;
  metadata: {
    battery_id: string;
    experiment_id: string;
    chemistry: ResearchMetadataEntry;
    nominal_capacity_ah: ResearchMetadataEntry;
    probe: ResearchMetadataEntry;
    channel: ResearchMetadataEntry;
    temperature: ResearchMetadataEntry;
    sampling_rate: ResearchMetadataEntry;
    acquisition_window: ResearchMetadataEntry;
    timebase: { status: string };
  };
  electrical: {
    status: string;
    record_count: number | null;
    cycle_count: number | null;
    step_count: number | null;
    voltage_range_v: [number, number] | null;
    current_range_a: [number, number] | null;
    voltage_sparkline_v: (number | null)[];
    current_sparkline_a: (number | null)[];
    cycles: {
      cycle_index_raw: number;
      charge_capacity_ah: number | null;
      discharge_capacity_ah: number | null;
      apparent_coulombic_efficiency_percent: number | null;
      protocol: string;
    }[];
  };
  ultrasound_tof: {
    status: string;
    tof_method_id: string;
    tof_definition_version: string | null;
    sampling_rate_hz: number | null;
    sampling_rate_verified: boolean;
    gate_calibration_id: string;
    gate_calibration_source: string;
    gate_calibration_version: number;
    surface_gate_id: string;
    surface_peak_sample_range: [number, number];
    bottom_gate_id: string;
    bottom_peak_sample_range: [number, number];
    artifact_status_counts: Record<string, number>;
    artifact_tof_us_summary: { min: number; median: number; max: number } | null;
    artifact_current: boolean;
    waveform_tof: { event_count: number | null; ambiguous_events: number | null; note: string };
    feature_target_eligible: { eligible_count: number | null; note: string };
  };
  signal_quality: {
    snr: { status: string; value: null; reason: string };
    saturation_check: { status: string; definition: string };
  };
  readiness_matrix: {
    acquisition: string;
    synchronization: string;
    tof: string;
    targets: string;
    modeling: string;
  };
  scientific_snapshot: {
    target: { target_id: string; readiness: string; note: string };
    leading_exploratory_candidate: {
      analysis_id: string;
      feature_name: string;
      method: string;
      coefficient: number | null;
      n: number | null;
      note: string;
    } | null;
    selected_features: string[];
    model_evidence: {
      dummy_first_conclusion: string | null;
      dummy_macro_mae: number | null;
      note: string;
    };
    feature_definition: ResearchFeatureDefinitionState;
  };
  model_comparison: {
    status: string;
    artifact_path: string;
    strategies: {
      strategy: string;
      macro_mae: number | null;
      macro_rmse: number | null;
      macro_r2: number | null;
      vs_dummy: number | null;
    }[];
    dummy: { strategy: string; macro_mae: number | null } | null;
    dummy_first_conclusion: string | null;
    feature_definition: ResearchFeatureDefinitionState;
  };
  limitations_first_screen: { code: string; severity: string; description: string; description_zh?: string }[];
  next_actions: { action_id: string; label: string; route: string }[];
  research_status_banner: { level: string; message: string };
}

export interface ResearchFeatureDefinitionState {
  feature_set_id: string;
  dataset_definition_version: string | null;
  current_policy: string;
  uses_previous_feature_definition: boolean;
  refresh_required: boolean;
  note: string;
}

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
  { method: "GET", path: "/feature-definitions" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/physical-features" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/feature-correlations" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/gate-calibration" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/splits" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/feature-analyses" },
  { method: "POST", path: "/experiments/{battery_id}/{experiment_id}/assistant/session" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/assistant/session/{session_id}" },
  { method: "POST", path: "/experiments/{battery_id}/{experiment_id}/assistant/session/{session_id}/message" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/targets" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/alignment-summary" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/alignment-samples" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/alignment-exclusions" },
  { method: "POST", path: "/experiments/{battery_id}/{experiment_id}/feature-label-preview" },
  { method: "POST", path: "/experiments/{battery_id}/{experiment_id}/feature-target-ranking" },
  { method: "POST", path: "/experiments/{battery_id}/{experiment_id}/gate-calibration" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/canonical-tof" },
  { method: "POST", path: "/experiments/{battery_id}/{experiment_id}/tof-gate-calibration" },
  { method: "POST", path: "/experiments/{battery_id}/{experiment_id}/sampling-parameter-submission" },
  { method: "POST", path: "/experiments/{battery_id}/{experiment_id}/sampling-parameter-submission/{submission_id}/retry-resume" },
  { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/research-overview" },
];

/** BRW-024R/025R v2 client 方法（插入到 client 对象内）。 */
