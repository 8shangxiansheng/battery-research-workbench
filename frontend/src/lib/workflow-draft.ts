import type { WorkflowContextPayload } from "../api/client";

export type AnalysisMode = "EXPLORATORY_FULL_DATA" | "TRAIN_ONLY_ML_SAFE";
export interface AnalysisDraft {
  targetId: string | null;
  features: string[];
  mode: AnalysisMode;
}

/** Restore the most recently committed analysis selection without persisting a draft. */
export function deriveAnalysisDraft(context: WorkflowContextPayload): AnalysisDraft {
  const target = context.steps.TARGET?.committed;
  const featureAnalysis = context.steps.FEATURES?.committed;
  const dataset = context.steps.DATASET?.committed;
  const committedFeatures = featureAnalysis?.selected_features;
  const datasetFeatures = dataset?.selected_features;
  const features = Array.isArray(committedFeatures)
    ? committedFeatures.filter((value): value is string => typeof value === "string")
    : Array.isArray(datasetFeatures)
      ? datasetFeatures.filter((value): value is string => typeof value === "string")
      : [];
  const targetId = typeof target?.target_id === "string" ? target.target_id : null;
  return {
    targetId: targetId === "soc_reference_percent" ? "reference_soc_percent" : targetId,
    features,
    mode: featureAnalysis?.analysis_mode === "TRAIN_ONLY_ML_SAFE"
      ? "TRAIN_ONLY_ML_SAFE"
      : "EXPLORATORY_FULL_DATA",
  };
}
