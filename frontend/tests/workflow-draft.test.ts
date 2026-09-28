import { describe, expect, it } from "vitest";
import type { WorkflowContextPayload } from "../src/api/client";
import { deriveAnalysisDraft } from "../src/lib/workflow-draft";

function workflow(overrides: Partial<WorkflowContextPayload> = {}): WorkflowContextPayload {
  return {
    schema_version: "workflow-context/1.0", battery_id: "CELL_001", experiment_id: "EXP_001",
    current_step: "DATASET", step_statuses: {},
    steps: {
      TARGET: { status: "COMPLETE", committed: { target_id: "reference_soc_percent" } },
      FEATURES: { status: "COMPLETE", committed: { analysis_mode: "TRAIN_ONLY_ML_SAFE", selected_features: ["tof_us", "amplitude_a_u"] } },
      DATASET: { status: "COMPLETE", committed: { selected_features: ["legacy_feature"] } },
    },
    recommended_next_action: null, pending_action: null, artifact_freshness: {},
    scientific_context: {}, assistant_context: {}, typed_actions: [],
    meta: { read_only: true, no_recomputation: true }, ...overrides,
  };
}

describe("Analysis workflow draft hydration", () => {
  it("restores target, latest committed feature selection, and ML-safe mode", () => {
    expect(deriveAnalysisDraft(workflow())).toEqual({
      targetId: "reference_soc_percent", features: ["tof_us", "amplitude_a_u"], mode: "TRAIN_ONLY_ML_SAFE",
    });
  });

  it("falls back to committed dataset features only when no feature analysis exists", () => {
    const context = workflow({ steps: {
      TARGET: { status: "COMPLETE", committed: { target_id: "reference_soc_percent" } },
      FEATURES: { status: "NOT_STARTED", committed: null },
      DATASET: { status: "COMPLETE", committed: { selected_features: ["tof_us"] } },
    } });
    expect(deriveAnalysisDraft(context).features).toEqual(["tof_us"]);
  });

  it("maps the workflow SOC target name to the canonical target API identifier", () => {
    const context = workflow({ steps: {
      TARGET: { status: "COMPLETE", committed: { target_id: "soc_reference_percent" } },
      FEATURES: { status: "COMPLETE", committed: { selected_features: ["tof_us"] } },
      DATASET: { status: "NOT_STARTED", committed: null },
    } });
    expect(deriveAnalysisDraft(context).targetId).toBe("reference_soc_percent");
  });
});
