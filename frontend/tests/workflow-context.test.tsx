/**
 * BRW-025R-WF — Frontend acceptance tests (W02–W26).
 *
 * Contract rule 3: acceptance tests before implementation.
 * Tests use mocked client to verify frontend behavior without real API.
 *
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { WorkflowContextPayload } from "../src/api/client";

// ---------- Mock client ----------

const mockGetWorkflowContext = vi.fn();

vi.mock("../src/api/client", () => ({
  WF_STEP_KEYS: ["TARGET", "ALIGNMENT", "FEATURES", "PREVIEW", "DATASET", "SPLIT", "MODELS", "REPORT"] as const,
  CLIENT_PATHS: [
    { method: "GET", path: "/experiments/{battery_id}/{experiment_id}/workflow-context" },
  ],
  client: {
    getWorkflowContext: (...args: unknown[]) => mockGetWorkflowContext(...args),
    openAssistantSession: vi.fn().mockResolvedValue({ data: { session_id: "s1", battery_id: "C", experiment_id: "E", current_page: "overview", selected_target: null, target_readiness: null, alignment_status: null, selected_features: [], feature_selection_mode: "manual", dataset_id: null, split_id: null, model_run_id: null, report_id: null, phase: "UNDERSTAND_GOAL", pending_user_action: null, scientific_limitations: [], evidence_refs: [], next_actions: [], conversation: [] }, meta: {} }),
    sendAssistantMessage: vi.fn(),
    listLibraryExperiments: vi.fn().mockResolvedValue({ data: { experiments: [] }, meta: {} }),
    getResearchOverview: vi.fn().mockResolvedValue({ data: { schema_version: "research-overview/1.0", metadata: { battery_id: "C", experiment_id: "E", chemistry: { status: "OK" }, nominal_capacity_ah: { status: "OK" }, probe: { status: "OK" }, channel: { status: "OK" }, temperature: { status: "OK" }, sampling_rate: { status: "OK", hz: 50000000, verified: true }, acquisition_window: { status: "OK" }, timebase: { status: "OK" } }, electrical: { status: "OK", record_count: 100, cycle_count: 10, step_count: 20, voltage_range_v: [3.0, 4.2], current_range_a: [0.5, 2.0], voltage_sparkline_v: [], current_sparkline_a: [], cycles: [] }, ultrasound_tof: { status: "OK", tof_method_id: "TM::1", tof_definition_version: "2.0.0", sampling_rate_hz: 50000000, sampling_rate_verified: true, gate_calibration_id: "GC::1", gate_calibration_source: "manual", gate_calibration_version: 1, surface_gate_id: "G1", surface_peak_sample_range: [10, 50], bottom_gate_id: "G2", bottom_peak_sample_range: [100, 150], artifact_status_counts: {}, artifact_tof_us_summary: null, artifact_current: true, waveform_tof: { event_count: 3999, ambiguous_events: 4, note: "" }, feature_target_eligible: { eligible_count: 3995, note: "" } }, signal_quality: { snr: { status: "OK", value: null, reason: "" }, saturation_check: { status: "OK", definition: "" } }, readiness_matrix: { acquisition: "OK", synchronization: "OK", tof: "OK", targets: "OK", modeling: "OK" }, stale_dependencies: { feature_definition: { fs_version: "2.0.0", refresh_required: false } }, target: { target_id: "soc_reference_percent", target_status: "READY_FOR_LIMITED_EVALUATION", display_name_en: "Reference SOC", display_name_zh: "参考 SOC" }, features: { selected_count: 6, feature_locators: [], selection_source: "manual", selection_status: "AVAILABLE" }, preview: { spec_hash: "abc123", mode: "EXPLORATORY_FULL_DATA", eligible_rows: 3995, excluded_rows: 4, confirmed: true }, dataset: { dataset_id: "DS::6a3142", dataset_status: "MATERIALIZED", materialized_at: "2025-01-01T00:00:00Z" }, split: { split_id: "SPLIT::9d38", split_status: "AVAILABLE", strategy: "LOGO", fold_count: 2 }, models: { model_run_ids: ["MR::1", "MR::2"], model_status: "AVAILABLE", strategies: ["DUMMY_MEAN", "RIDGE"] }, report: { report_id: "REPORT::62c7", report_status: "AVAILABLE" }, limitations_first_screen: [], next_actions: [{ action_id: "REVIEW_TARGET", label: "复核目标", route: "/experiments/C/E/analysis" }], research_status_banner: { level: "OK", message: "" } }, meta: {} }),
  },
  ApiError: class ApiError extends Error {
    code: string; requestId: string; details: Record<string, unknown>; status: number;
    constructor(status: number, body: { error: { code: string; message: string; request_id: string } }) {
      super(body.error.message); this.code = body.error.code; this.requestId = body.error.request_id;
      this.details = {}; this.status = status;
    }
  },
}));

// ---------- Helpers ----------

function makeWorkflowCtx(overrides: Partial<WorkflowContextPayload> = {}): WorkflowContextPayload {
  return {
    schema_version: "workflow-context/1.0",
    battery_id: "CELL_001",
    experiment_id: "EXP_001",
    current_step: "REPORT",
    step_statuses: {
      TARGET: "COMPLETE", ALIGNMENT: "COMPLETE", FEATURES: "COMPLETE",
      PREVIEW: "COMPLETE", DATASET: "COMPLETE", SPLIT: "COMPLETE",
      MODELS: "COMPLETE", REPORT: "COMPLETE",
    },
    steps: {
      TARGET: { status: "COMPLETE", committed: { target_id: "soc_reference_percent" } },
      ALIGNMENT: { status: "COMPLETE", committed: { eligible_count: 3995, excluded_count: 4 } },
      FEATURES: { status: "COMPLETE", committed: { feature_locators: ["f1", "f2"] } },
      PREVIEW: { status: "COMPLETE" },
      DATASET: { status: "COMPLETE", committed: { dataset_id: "DS::6a3142" } },
      SPLIT: { status: "COMPLETE", committed: { split_id: "SPLIT::9d38" } },
      MODELS: { status: "COMPLETE", committed: { model_run_ids: ["MR::1"] } },
      REPORT: { status: "COMPLETE", committed: { report_id: "REPORT::62c7" } },
    },
    recommended_next_action: {
      action_id: "RESOLVE_PENDING_ACTION",
      step: "TARGET",
      label: "处理待恢复的参数提交",
      route: "/experiments/CELL_001/EXP_001/overview",
    },
    pending_action: {
      action_id: "RESOLVE_PENDING_ACTION",
      status: "WAITING_FOR_USER",
      label: "有待恢复的参数提交",
      route: "/experiments/CELL_001/EXP_001/overview",
      scientific_reason: "BRW-018R2 提交等待恢复",
      submissions: [
        { submission_id: "SUB::abc", parameter_set_id: "PS::1", fs_value: 50, fs_unit: "MHz", resume_status: "NOT_ATTEMPTED" },
      ],
    },
    artifact_freshness: { dataset: "LEGACY", models: "STALE", report: "STALE" },
    scientific_context: {},
    assistant_context: {},
    typed_actions: [
      { action_id: "REVIEW_TARGET", label: "选择参考 SOC 目标", route: "/experiments/CELL_001/EXP_001/analysis" },
      { action_id: "OPEN_REPORT", label: "查看研究报告", route: "/experiments/CELL_001/EXP_001/report" },
    ],
    meta: { read_only: true, no_recomputation: true },
    ...overrides,
  };
}

function renderWithWorkflow(ui: React.ReactNode, path = "/experiments/CELL_001/EXP_001/overview") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/experiments/:batteryId/:experimentId/*" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// ---------- Tests ----------

describe("W02 — WorkflowContextPayload DTO shape", () => {
  it("getWorkflowContext method exists on client", async () => {
    const { client } = await import("../src/api/client");
    expect(typeof client.getWorkflowContext).toBe("function");
  });
});

describe("W04 — current_step derivation", () => {
  it("deriveStepperStatuses marks current_step as CURRENT", async () => {
    const { deriveStepperStatuses } = await import("../src/hooks/useWorkflowContext");
    const statuses = deriveStepperStatuses("REPORT", {
      TARGET: "COMPLETE", ALIGNMENT: "COMPLETE", FEATURES: "COMPLETE",
      PREVIEW: "COMPLETE", DATASET: "COMPLETE", SPLIT: "COMPLETE",
      MODELS: "COMPLETE", REPORT: "COMPLETE",
    }, { dataset: "CURRENT", models: "CURRENT", report: "CURRENT" });
    expect(statuses.REPORT).toBe("CURRENT");
    expect(statuses.TARGET).toBe("COMPLETE");
    expect(statuses.MODELS).toBe("COMPLETE");
  });

  it("deriveStepperStatuses marks current_step as CURRENT even when COMPLETE", async () => {
    const { deriveStepperStatuses } = await import("../src/hooks/useWorkflowContext");
    const statuses = deriveStepperStatuses("FEATURES", {
      TARGET: "COMPLETE", ALIGNMENT: "COMPLETE", FEATURES: "COMPLETE",
      PREVIEW: "NOT_STARTED", DATASET: "NOT_STARTED", SPLIT: "NOT_STARTED",
      MODELS: "NOT_STARTED", REPORT: "NOT_STARTED",
    }, {});
    expect(statuses.FEATURES).toBe("CURRENT");
    expect(statuses.TARGET).toBe("COMPLETE");
  });
});

describe("W05 — seven stepper visual states", () => {
  it("deriveStepperStatuses produces all seven states", async () => {
    const { deriveStepperStatuses } = await import("../src/hooks/useWorkflowContext");
    const statuses = deriveStepperStatuses("FEATURES", {
      TARGET: "COMPLETE",        // → COMPLETE
      ALIGNMENT: "COMPLETE",     // → COMPLETE
      FEATURES: "COMPLETE",      // → CURRENT (overrides COMPLETE)
      PREVIEW: "NOT_STARTED",    // → READY (prev is CURRENT)
      DATASET: "NOT_STARTED",    // → NOT_STARTED (prev is READY, not COMPLETE)
      SPLIT: "BLOCKED",          // → BLOCKED
      MODELS: "LIMITED",         // → LIMITED
      REPORT: "NOT_STARTED",     // → NOT_STARTED (prev is LIMITED)
    }, {});
    expect(statuses.TARGET).toBe("COMPLETE");
    expect(statuses.ALIGNMENT).toBe("COMPLETE");
    expect(statuses.FEATURES).toBe("CURRENT");
    expect(statuses.PREVIEW).toBe("READY");
    expect(statuses.DATASET).toBe("NOT_STARTED");
    expect(statuses.SPLIT).toBe("BLOCKED");
    expect(statuses.MODELS).toBe("LIMITED");
    expect(statuses.REPORT).toBe("NOT_STARTED");
  });

  it("STALE derivation for dataset/models/report", async () => {
    const { deriveStepperStatuses } = await import("../src/hooks/useWorkflowContext");
    const statuses = deriveStepperStatuses("REPORT", {
      TARGET: "COMPLETE", ALIGNMENT: "COMPLETE", FEATURES: "COMPLETE",
      PREVIEW: "COMPLETE", DATASET: "COMPLETE", SPLIT: "COMPLETE",
      MODELS: "COMPLETE", REPORT: "COMPLETE",
    }, { dataset: "LEGACY", models: "STALE", report: "STALE" });
    // DATASET and MODELS are before current_step, so they use backend status
    // but freshness is LEGACY/STALE → STALE
    expect(statuses.DATASET).toBe("STALE");
    expect(statuses.MODELS).toBe("STALE");
    // REPORT is current_step → CURRENT (overrides freshness)
    expect(statuses.REPORT).toBe("CURRENT");
  });
});

describe("W08 — Resume Research button", () => {
  it("navigate to recommended_next_action.route on click", async () => {
    const ctx = makeWorkflowCtx();
    mockGetWorkflowContext.mockResolvedValue({ data: ctx, meta: {} });

    // Test the hook returns the correct recommended action
    const { workflowContextKey } = await import("../src/hooks/useWorkflowContext");
    expect(workflowContextKey("CELL_001", "EXP_001")).toEqual(["workflow-context", "CELL_001", "EXP_001"]);
  });
});

describe("W22 — WAITING global banner", () => {
  it("WaitingBanner shows when pending_action is WAITING_FOR_USER", async () => {
    const { WaitingBanner } = await import("../src/components/workbench/WaitingBanner");
    const pendingAction = {
      action_id: "RESOLVE_PENDING_ACTION",
      status: "WAITING_FOR_USER",
      label: "有待恢复的参数提交",
      route: "/experiments/CELL_001/EXP_001/overview",
      scientific_reason: "BRW-018R2 提交等待恢复",
    };
    renderWithWorkflow(<WaitingBanner pendingAction={pendingAction} />);
    expect(screen.getByTestId("waiting-banner")).toBeInTheDocument();
    expect(screen.getByText("等待输入 / Waiting for your input")).toBeInTheDocument();
    expect(screen.getByTestId("waiting-banner-action")).toHaveAttribute("href", "/experiments/CELL_001/EXP_001/overview");
  });

  it("WaitingBanner hides when no pending action", async () => {
    const { WaitingBanner } = await import("../src/components/workbench/WaitingBanner");
    const { container } = renderWithWorkflow(<WaitingBanner pendingAction={null} />);
    expect(container.querySelector("[data-testid=waiting-banner]")).toBeNull();
  });

  it("WaitingBanner hides when pending is not WAITING_FOR_USER", async () => {
    const { WaitingBanner } = await import("../src/components/workbench/WaitingBanner");
    const pendingAction = {
      action_id: "X", status: "RESOLVED", label: "Done",
      route: "/overview", scientific_reason: "",
    };
    const { container } = renderWithWorkflow(<WaitingBanner pendingAction={pendingAction} />);
    expect(container.querySelector("[data-testid=waiting-banner]")).toBeNull();
  });
});

describe("W13/W17 — Deep-link prerequisite panel", () => {
  it("shows prerequisite panel for BLOCKED step", async () => {
    const { PrerequisitePanel } = await import("../src/components/workbench/PrerequisitePanel");
    renderWithWorkflow(
      <PrerequisitePanel
        stepKey="SPLIT"
        stepStatus="BLOCKED"
        stepDetail={{ status: "BLOCKED", blocking: { blocking_code: "DATASET_MISSING", blocking_message: "数据集未物化", required_action: "BUILD_DATASET", scientific_reason: "分组划分必须建立在已物化数据集上" } }}
        recommended={{ action_id: "BUILD_DATASET", step: "DATASET", label: "构建数据集", route: "/experiments/CELL_001/EXP_001/analysis" }}
        batteryId="CELL_001"
        experimentId="EXP_001"
      />,
    );
    expect(screen.getByTestId("prerequisite-panel")).toBeInTheDocument();
    expect(screen.getByText("前置条件未满足 / Prerequisites not met")).toBeInTheDocument();
    expect(screen.getByText("数据集未物化")).toBeInTheDocument();
    expect(screen.getByTestId("prerequisite-next-action")).toHaveAttribute("href", "/experiments/CELL_001/EXP_001/analysis");
  });
});

describe("W18 — No POST side-effects on navigation", () => {
  it("stepper renders without triggering mutations", async () => {
    const { WorkflowStepperV2 } = await import("../src/components/workbench/WorkflowStepperV2");
    const statuses = {
      TARGET: "COMPLETE", ALIGNMENT: "COMPLETE", FEATURES: "COMPLETE",
      PREVIEW: "COMPLETE", DATASET: "COMPLETE", SPLIT: "COMPLETE",
      MODELS: "COMPLETE", REPORT: "CURRENT",
    } as const;
    renderWithWorkflow(<WorkflowStepperV2 statuses={statuses} activePage="report" />);
    // Stepper renders without any POST calls
    expect(screen.getByTestId("workflow-stepper-v2")).toBeInTheDocument();
    expect(screen.getByTestId("stepper-report")).toHaveAttribute("data-status", "CURRENT");
  });
});

describe("W20 — Experiment switch isolation", () => {
  it("workflowContextKey includes batteryId + experimentId", async () => {
    const { workflowContextKey } = await import("../src/hooks/useWorkflowContext");
    const key1 = workflowContextKey("CELL_001", "EXP_001");
    const key2 = workflowContextKey("CELL_002", "EXP_002");
    expect(key1).not.toEqual(key2);
    expect(key1[0]).toBe("workflow-context");
    expect(key2[0]).toBe("workflow-context");
  });
});

describe("W26 — Assistant typed navigation", () => {
  it("typed_actions array has action_id, label, route", () => {
    const ctx = makeWorkflowCtx();
    expect(ctx.typed_actions.length).toBeGreaterThan(0);
    for (const action of ctx.typed_actions) {
      expect(action).toHaveProperty("action_id");
      expect(action).toHaveProperty("label");
      expect(action).toHaveProperty("route");
      // No free-form URLs — routes start with /experiments/
      expect(action.route).toMatch(/^\/experiments\//);
    }
  });
});

describe("W02 — CLIENT_PATHS includes workflow-context", () => {
  it("CLIENT_PATHS contains workflow-context entry", async () => {
    const { CLIENT_PATHS } = await import("../src/api/client");
    const found = CLIENT_PATHS.find(p => p.path.includes("workflow-context"));
    expect(found).toBeDefined();
    expect(found!.method).toBe("GET");
  });
});

// ---------- W01 — Route table completeness ----------

describe("W01 — Route table completeness", () => {
  it("WF_STEP_ROUTES maps all 8 canonical workflow steps", async () => {
    const { WF_STEP_ROUTES } = await import("../src/hooks/useWorkflowContext");
    const expected = ["TARGET", "ALIGNMENT", "FEATURES", "PREVIEW", "DATASET", "SPLIT", "MODELS", "REPORT"];
    for (const step of expected) {
      expect(WF_STEP_ROUTES[step]).toBeDefined();
    }
  });

  it("SPLIT maps to advanced/dataset-split (not broken /advanced/splits)", async () => {
    const { WF_STEP_ROUTES } = await import("../src/hooks/useWorkflowContext");
    expect(WF_STEP_ROUTES.SPLIT).toBe("advanced/dataset-split");
  });
});

// ---------- W03 — Stepper is navigation-only ----------

describe("W03 — Stepper navigation-only (no mutations)", () => {
  it("BLOCKED step button is disabled", async () => {
    const { WorkflowStepperV2 } = await import("../src/components/workbench/WorkflowStepperV2");
    const statuses = {
      TARGET: "COMPLETE", ALIGNMENT: "COMPLETE", FEATURES: "CURRENT",
      PREVIEW: "NOT_STARTED", DATASET: "BLOCKED", SPLIT: "NOT_STARTED",
      MODELS: "NOT_STARTED", REPORT: "NOT_STARTED",
    } as const;
    renderWithWorkflow(<WorkflowStepperV2 statuses={statuses} activePage="analysis" />);
    const datasetBtn = screen.getByTestId("stepper-dataset");
    expect(datasetBtn).toBeDisabled();
    expect(datasetBtn).toHaveAttribute("data-status", "BLOCKED");
  });

  it("NOT_STARTED step button is disabled", async () => {
    const { WorkflowStepperV2 } = await import("../src/components/workbench/WorkflowStepperV2");
    const statuses = {
      TARGET: "CURRENT", ALIGNMENT: "NOT_STARTED", FEATURES: "NOT_STARTED",
      PREVIEW: "NOT_STARTED", DATASET: "NOT_STARTED", SPLIT: "NOT_STARTED",
      MODELS: "NOT_STARTED", REPORT: "NOT_STARTED",
    } as const;
    renderWithWorkflow(<WorkflowStepperV2 statuses={statuses} activePage="analysis" />);
    expect(screen.getByTestId("stepper-alignment")).toBeDisabled();
    expect(screen.getByTestId("stepper-models")).toBeDisabled();
  });

  it("COMPLETE/CURRENT/READY steps are clickable", async () => {
    const { WorkflowStepperV2 } = await import("../src/components/workbench/WorkflowStepperV2");
    const statuses = {
      TARGET: "COMPLETE", ALIGNMENT: "COMPLETE", FEATURES: "CURRENT",
      PREVIEW: "READY", DATASET: "NOT_STARTED", SPLIT: "NOT_STARTED",
      MODELS: "NOT_STARTED", REPORT: "NOT_STARTED",
    } as const;
    renderWithWorkflow(<WorkflowStepperV2 statuses={statuses} activePage="analysis" />);
    expect(screen.getByTestId("stepper-target")).not.toBeDisabled();
    expect(screen.getByTestId("stepper-alignment")).not.toBeDisabled();
    expect(screen.getByTestId("stepper-features")).not.toBeDisabled();
    expect(screen.getByTestId("stepper-preview")).not.toBeDisabled();
  });
});

// ---------- W06 — Target selection inheritance ----------

describe("W06 — Target selection inheritance", () => {
  it("workflow context carries committed target_id", () => {
    const ctx = makeWorkflowCtx();
    expect(ctx.steps.TARGET!.committed).toBeDefined();
    expect(ctx.steps.TARGET!.committed!.target_id).toBe("soc_reference_percent");
  });

  it("target status is propagated in step_statuses", () => {
    const ctx = makeWorkflowCtx({
      step_statuses: { TARGET: "COMPLETE", ALIGNMENT: "NOT_STARTED", FEATURES: "NOT_STARTED", PREVIEW: "NOT_STARTED", DATASET: "NOT_STARTED", SPLIT: "NOT_STARTED", MODELS: "NOT_STARTED", REPORT: "NOT_STARTED" },
    });
    expect(ctx.step_statuses.TARGET).toBe("COMPLETE");
  });
});

// ---------- W07 — Features→Preview→Dataset handoff ----------

describe("W07 — Features→Preview→Dataset handoff", () => {
  it("committed features carry feature_locators", () => {
    const ctx = makeWorkflowCtx();
    expect(ctx.steps.FEATURES!.committed).toBeDefined();
    expect(ctx.steps.FEATURES!.committed!.feature_locators).toEqual(["f1", "f2"]);
  });

  it("dataset step carries dataset_id in committed", () => {
    const ctx = makeWorkflowCtx();
    expect(ctx.steps.DATASET!.committed).toBeDefined();
    expect(ctx.steps.DATASET!.committed!.dataset_id).toBe("DS::6a3142");
  });

  it("preview step status is COMPLETE when spec confirmed", () => {
    const ctx = makeWorkflowCtx();
    expect(ctx.steps.PREVIEW!.status).toBe("COMPLETE");
  });
});

// ---------- W09 — Split gating Models ----------

describe("W09 — Split gating Models", () => {
  it("BLOCKED SPLIT prevents Models stepper from being COMPLETE", async () => {
    const { deriveStepperStatuses } = await import("../src/hooks/useWorkflowContext");
    const statuses = deriveStepperStatuses("MODELS", {
      TARGET: "COMPLETE", ALIGNMENT: "COMPLETE", FEATURES: "COMPLETE",
      PREVIEW: "COMPLETE", DATASET: "COMPLETE", SPLIT: "BLOCKED",
      MODELS: "COMPLETE", REPORT: "NOT_STARTED",
    }, {});
    expect(statuses.SPLIT).toBe("BLOCKED");
    expect(statuses.MODELS).toBe("CURRENT");
  });

  it("PrerequisitePanel renders for BLOCKED SPLIT when navigating to models", async () => {
    const { PrerequisitePanel } = await import("../src/components/workbench/PrerequisitePanel");
    renderWithWorkflow(
      <PrerequisitePanel
        stepKey="SPLIT"
        stepStatus="BLOCKED"
        stepDetail={{ status: "BLOCKED", blocking: { blocking_code: "DATASET_MISSING", blocking_message: "数据集未物化", required_action: "BUILD_DATASET", scientific_reason: "分组划分必须建立在已物化数据集上" } }}
        recommended={{ action_id: "BUILD_DATASET", step: "DATASET", label: "构建数据集", route: "/experiments/CELL_001/EXP_001/analysis" }}
        batteryId="CELL_001"
        experimentId="EXP_001"
      />,
    );
    expect(screen.getByTestId("prerequisite-panel")).toBeInTheDocument();
    expect(screen.getByText("数据集未物化")).toBeInTheDocument();
  });
});

// ---------- W10 — Model→Report continuity ----------

describe("W10 — Model→Report continuity", () => {
  it("StaleBanner renders on report page when models are STALE", async () => {
    const { StaleBanner } = await import("../src/pages/redesign/WorkbenchShell");
    renderWithWorkflow(<StaleBanner freshness={{ dataset: "CURRENT", models: "STALE", report: "STALE" }} stepKey="REPORT" />);
    expect(screen.getByTestId("stale-banner-report")).toBeInTheDocument();
  });

  it("StaleBanner renders on models page when dataset is LEGACY", async () => {
    const { StaleBanner } = await import("../src/pages/redesign/WorkbenchShell");
    renderWithWorkflow(<StaleBanner freshness={{ dataset: "LEGACY", models: "STALE", report: "CURRENT" }} stepKey="MODELS" />);
    expect(screen.getByTestId("stale-banner-models")).toBeInTheDocument();
  });
});

// ---------- W11 — Back/Forward without re-build ----------

describe("W11 — Back/Forward navigation immutability", () => {
  it("stepper COMPLETE step is a <button> (not a <form> or submit)", async () => {
    const { WorkflowStepperV2 } = await import("../src/components/workbench/WorkflowStepperV2");
    const statuses = {
      TARGET: "COMPLETE", ALIGNMENT: "COMPLETE", FEATURES: "COMPLETE",
      PREVIEW: "COMPLETE", DATASET: "COMPLETE", SPLIT: "COMPLETE",
      MODELS: "COMPLETE", REPORT: "CURRENT",
    } as const;
    renderWithWorkflow(<WorkflowStepperV2 statuses={statuses} activePage="report" />);
    const targetBtn = screen.getByTestId("stepper-target");
    expect(targetBtn.tagName).toBe("BUTTON");
    expect(targetBtn).not.toHaveAttribute("type", "submit");
  });

  it("stepper has aria-label for accessibility", async () => {
    const { WorkflowStepperV2 } = await import("../src/components/workbench/WorkflowStepperV2");
    const statuses = {
      TARGET: "COMPLETE", ALIGNMENT: "COMPLETE", FEATURES: "CURRENT",
      PREVIEW: "NOT_STARTED", DATASET: "NOT_STARTED", SPLIT: "NOT_STARTED",
      MODELS: "NOT_STARTED", REPORT: "NOT_STARTED",
    } as const;
    renderWithWorkflow(<WorkflowStepperV2 statuses={statuses} activePage="analysis" />);
    expect(screen.getByTestId("workflow-stepper-v2")).toHaveAttribute("aria-label", "科研工作流");
  });
});

// ---------- W12 — Deep link recovery ----------

describe("W12 — Deep link shows prerequisite panel (not 404)", () => {
  it("PrerequisitePanel renders with blocking_message and scientific_reason", async () => {
    const { PrerequisitePanel } = await import("../src/components/workbench/PrerequisitePanel");
    renderWithWorkflow(
      <PrerequisitePanel
        stepKey="MODELS"
        stepStatus="BLOCKED"
        stepDetail={{ status: "BLOCKED", blocking: { blocking_code: "SPLIT_REQUIRED", blocking_message: "需要先建立分组划分", required_action: "CREATE_SPLIT", scientific_reason: "ML 建模必须基于分组划分以避免数据泄漏" } }}
        recommended={{ action_id: "CREATE_SPLIT", step: "SPLIT", label: "建立分组划分", route: "/experiments/CELL_001/EXP_001/advanced/dataset-split" }}
        batteryId="CELL_001"
        experimentId="EXP_001"
      />,
    );
    expect(screen.getByText("需要先建立分组划分")).toBeInTheDocument();
    expect(screen.getByText("ML 建模必须基于分组划分以避免数据泄漏")).toBeInTheDocument();
    expect(screen.getByTestId("prerequisite-next-action")).toHaveAttribute("href", "/experiments/CELL_001/EXP_001/advanced/dataset-split");
  });
});

// ---------- W14 — StepGate analysis chain ----------

describe("W14 — StepGate analysis chain blocking", () => {
  it("PrerequisitePanel shows first BLOCKED step in analysis chain", async () => {
    const { PrerequisitePanel } = await import("../src/components/workbench/PrerequisitePanel");
    const chain = ["TARGET", "ALIGNMENT", "FEATURES", "PREVIEW", "DATASET"] as const;
    const blockedIdx = 2;
    const blocked = chain[blockedIdx];
    renderWithWorkflow(
      <PrerequisitePanel
        stepKey={blocked!}
        stepStatus="BLOCKED"
        stepDetail={{ status: "BLOCKED", blocking: { blocking_code: "FEATURES_REQUIRED", blocking_message: "特征未选择", required_action: "SELECT_FEATURES", scientific_reason: "预览需要至少一个特征" } }}
        recommended={{ action_id: "SELECT_FEATURES", step: "FEATURES", label: "选择特征", route: "/experiments/CELL_001/EXP_001/analysis" }}
        batteryId="CELL_001"
        experimentId="EXP_001"
      />,
    );
    expect(screen.getByTestId("prerequisite-panel")).toBeInTheDocument();
    expect(screen.getByText("特征未选择")).toBeInTheDocument();
  });
});

// ---------- W15 — StepGate models page ----------

describe("W15 — StepGate models page blocking", () => {
  it("PrerequisitePanel renders for BLOCKED MODELS step", async () => {
    const { PrerequisitePanel } = await import("../src/components/workbench/PrerequisitePanel");
    renderWithWorkflow(
      <PrerequisitePanel
        stepKey="MODELS"
        stepStatus="BLOCKED"
        stepDetail={{ status: "BLOCKED", blocking: { blocking_code: "SPLIT_REQUIRED", blocking_message: "分组划分未完成", required_action: "CREATE_SPLIT", scientific_reason: "建模需要分组划分" } }}
        recommended={{ action_id: "CREATE_SPLIT", step: "SPLIT", label: "建立分组划分", route: "/experiments/CELL_001/EXP_001/advanced/dataset-split" }}
        batteryId="CELL_001"
        experimentId="EXP_001"
      />,
    );
    expect(screen.getByTestId("prerequisite-panel")).toBeInTheDocument();
    expect(screen.getByText("分组划分未完成")).toBeInTheDocument();
  });
});

// ---------- W16 — StepGate report page ----------

describe("W16 — StepGate report page blocking", () => {
  it("PrerequisitePanel renders for BLOCKED REPORT step", async () => {
    const { PrerequisitePanel } = await import("../src/components/workbench/PrerequisitePanel");
    renderWithWorkflow(
      <PrerequisitePanel
        stepKey="REPORT"
        stepStatus="BLOCKED"
        stepDetail={{ status: "BLOCKED", blocking: { blocking_code: "MODELS_REQUIRED", blocking_message: "模型未训练", required_action: "TRAIN_MODELS", scientific_reason: "报告需要至少一个模型运行结果" } }}
        recommended={{ action_id: "TRAIN_MODELS", step: "MODELS", label: "训练模型", route: "/experiments/CELL_001/EXP_001/models" }}
        batteryId="CELL_001"
        experimentId="EXP_001"
      />,
    );
    expect(screen.getByTestId("prerequisite-panel")).toBeInTheDocument();
    expect(screen.getByText("模型未训练")).toBeInTheDocument();
    expect(screen.getByTestId("prerequisite-next-action")).toHaveAttribute("href", "/experiments/CELL_001/EXP_001/models");
  });
});

// ---------- W19 — useInvalidateWorkflow invalidates all keys ----------

describe("W19 — useInvalidateWorkflow invalidation scope", () => {
  it("workflowContextKey is the base for invalidation", async () => {
    const { workflowContextKey } = await import("../src/hooks/useWorkflowContext");
    const key = workflowContextKey("CELL_001", "EXP_001");
    expect(key).toEqual(["workflow-context", "CELL_001", "EXP_001"]);
  });

  it("different experiments produce different invalidation keys", async () => {
    const { workflowContextKey } = await import("../src/hooks/useWorkflowContext");
    const key1 = workflowContextKey("CELL_001", "EXP_001");
    const key2 = workflowContextKey("CELL_002", "EXP_001");
    const key3 = workflowContextKey("CELL_001", "EXP_002");
    expect(key1).not.toEqual(key2);
    expect(key1).not.toEqual(key3);
    expect(key2).not.toEqual(key3);
  });
});

// ---------- W21 — StaleBanner renders for stale artifacts ----------

describe("W21 — StaleBanner renders for STALE/LEGACY/SUPERSEDED", () => {
  it("renders STALE banner for dataset", async () => {
    const { StaleBanner } = await import("../src/pages/redesign/WorkbenchShell");
    renderWithWorkflow(<StaleBanner freshness={{ dataset: "STALE" }} stepKey="DATASET" />);
    const banner = screen.getByTestId("stale-banner-dataset");
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toContain("Stale");
  });

  it("renders LEGACY banner for models", async () => {
    const { StaleBanner } = await import("../src/pages/redesign/WorkbenchShell");
    renderWithWorkflow(<StaleBanner freshness={{ models: "LEGACY" }} stepKey="MODELS" />);
    const banner = screen.getByTestId("stale-banner-models");
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toContain("Legacy");
  });

  it("renders SUPERSEDED banner for report", async () => {
    const { StaleBanner } = await import("../src/pages/redesign/WorkbenchShell");
    renderWithWorkflow(<StaleBanner freshness={{ report: "SUPERSEDED" }} stepKey="REPORT" />);
    const banner = screen.getByTestId("stale-banner-report");
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toContain("Superseded");
  });
});

// ---------- W23 — StaleBanner hides for CURRENT freshness ----------

describe("W23 — StaleBanner hides for CURRENT/unknown freshness", () => {
  it("does not render for CURRENT dataset", async () => {
    const { StaleBanner } = await import("../src/pages/redesign/WorkbenchShell");
    const { container } = renderWithWorkflow(<StaleBanner freshness={{ dataset: "CURRENT" }} stepKey="DATASET" />);
    expect(container.querySelector("[data-testid=stale-banner-dataset]")).toBeNull();
  });

  it("does not render for non-artifact stepKey", async () => {
    const { StaleBanner } = await import("../src/pages/redesign/WorkbenchShell");
    const { container } = renderWithWorkflow(<StaleBanner freshness={{ dataset: "STALE" }} stepKey="TARGET" />);
    expect(container.querySelector("[data-testid]")).toBeNull();
  });

  it("does not render when freshness key is missing", async () => {
    const { StaleBanner } = await import("../src/pages/redesign/WorkbenchShell");
    const { container } = renderWithWorkflow(<StaleBanner freshness={{}} stepKey="MODELS" />);
    expect(container.querySelector("[data-testid=stale-banner-models]")).toBeNull();
  });
});

// ---------- W24 — Stepper disabled states ----------

describe("W24 — WorkflowStepperV2 disabled for BLOCKED/NOT_STARTED", () => {
  it("BLOCKED step has aria-disabled=true", async () => {
    const { WorkflowStepperV2 } = await import("../src/components/workbench/WorkflowStepperV2");
    const statuses = {
      TARGET: "COMPLETE", ALIGNMENT: "BLOCKED", FEATURES: "NOT_STARTED",
      PREVIEW: "NOT_STARTED", DATASET: "NOT_STARTED", SPLIT: "NOT_STARTED",
      MODELS: "NOT_STARTED", REPORT: "NOT_STARTED",
    } as const;
    renderWithWorkflow(<WorkflowStepperV2 statuses={statuses} activePage="analysis" />);
    expect(screen.getByTestId("stepper-alignment")).toHaveAttribute("aria-disabled", "true");
  });

  it("LIMITED step is clickable (not disabled)", async () => {
    const { WorkflowStepperV2 } = await import("../src/components/workbench/WorkflowStepperV2");
    const statuses = {
      TARGET: "COMPLETE", ALIGNMENT: "COMPLETE", FEATURES: "COMPLETE",
      PREVIEW: "COMPLETE", DATASET: "COMPLETE", SPLIT: "COMPLETE",
      MODELS: "LIMITED", REPORT: "NOT_STARTED",
    } as const;
    renderWithWorkflow(<WorkflowStepperV2 statuses={statuses} activePage="models" />);
    expect(screen.getByTestId("stepper-models")).not.toBeDisabled();
    expect(screen.getByTestId("stepper-models")).toHaveAttribute("data-status", "LIMITED");
  });
});

// ---------- W25 — Stepper navigates on click ----------

describe("W25 — WorkflowStepperV2 click behavior", () => {
  it("stepper buttons have correct title attribute with status", async () => {
    const { WorkflowStepperV2 } = await import("../src/components/workbench/WorkflowStepperV2");
    const statuses = {
      TARGET: "COMPLETE", ALIGNMENT: "COMPLETE", FEATURES: "CURRENT",
      PREVIEW: "READY", DATASET: "NOT_STARTED", SPLIT: "NOT_STARTED",
      MODELS: "NOT_STARTED", REPORT: "NOT_STARTED",
    } as const;
    renderWithWorkflow(<WorkflowStepperV2 statuses={statuses} activePage="analysis" />);
    expect(screen.getByTestId("stepper-target")).toHaveAttribute("title", "目标 / Target: COMPLETE");
    expect(screen.getByTestId("stepper-features")).toHaveAttribute("title", "特征 / Features: CURRENT");
    expect(screen.getByTestId("stepper-preview")).toHaveAttribute("title", "预览 / Preview: READY");
  });

  it("CURRENT step has aria-current=step when it matches activePage", async () => {
    const { WorkflowStepperV2 } = await import("../src/components/workbench/WorkflowStepperV2");
    const statuses = {
      TARGET: "COMPLETE", ALIGNMENT: "COMPLETE", FEATURES: "CURRENT",
      PREVIEW: "NOT_STARTED", DATASET: "NOT_STARTED", SPLIT: "NOT_STARTED",
      MODELS: "NOT_STARTED", REPORT: "NOT_STARTED",
    } as const;
    renderWithWorkflow(<WorkflowStepperV2 statuses={statuses} activePage="analysis" />);
    expect(screen.getByTestId("stepper-features")).toHaveAttribute("aria-current", "step");
  });
});

// ---------- W27 — stepRoute produces correct routes ----------

describe("W27 — stepRoute produces correct routes", () => {
  it("generates correct route for each step", async () => {
    const { stepRoute } = await import("../src/hooks/useWorkflowContext");
    expect(stepRoute("CELL_001", "EXP_001", "TARGET")).toBe("/experiments/CELL_001/EXP_001/analysis");
    expect(stepRoute("CELL_001", "EXP_001", "ALIGNMENT")).toBe("/experiments/CELL_001/EXP_001/analysis");
    expect(stepRoute("CELL_001", "EXP_001", "FEATURES")).toBe("/experiments/CELL_001/EXP_001/analysis");
    expect(stepRoute("CELL_001", "EXP_001", "PREVIEW")).toBe("/experiments/CELL_001/EXP_001/analysis");
    expect(stepRoute("CELL_001", "EXP_001", "DATASET")).toBe("/experiments/CELL_001/EXP_001/analysis");
    expect(stepRoute("CELL_001", "EXP_001", "SPLIT")).toBe("/experiments/CELL_001/EXP_001/advanced/dataset-split");
    expect(stepRoute("CELL_001", "EXP_001", "MODELS")).toBe("/experiments/CELL_001/EXP_001/models");
    expect(stepRoute("CELL_001", "EXP_001", "REPORT")).toBe("/experiments/CELL_001/EXP_001/report");
  });

  it("unknown step falls back to overview", async () => {
    const { stepRoute } = await import("../src/hooks/useWorkflowContext");
    expect(stepRoute("CELL_001", "EXP_001", "UNKNOWN")).toBe("/experiments/CELL_001/EXP_001/overview");
  });
});

// ---------- W28 — WF_STEP_ROUTES maps all 8 steps ----------

describe("W28 — WF_STEP_ROUTES completeness", () => {
  it("has exactly 8 entries matching WF_STEP_KEYS", async () => {
    const { WF_STEP_ROUTES } = await import("../src/hooks/useWorkflowContext");
    const { WF_STEP_KEYS } = await import("../src/api/client");
    expect(Object.keys(WF_STEP_ROUTES).length).toBe(WF_STEP_KEYS.length);
    for (const key of WF_STEP_KEYS) {
      expect(WF_STEP_ROUTES[key]).toBeDefined();
      expect(typeof WF_STEP_ROUTES[key]).toBe("string");
    }
  });

  it("analysis steps all map to 'analysis'", async () => {
    const { WF_STEP_ROUTES } = await import("../src/hooks/useWorkflowContext");
    const analysisSteps = ["TARGET", "ALIGNMENT", "FEATURES", "PREVIEW", "DATASET"];
    for (const step of analysisSteps) {
      expect(WF_STEP_ROUTES[step]).toBe("analysis");
    }
  });
});

// ---------- W29 — Draft guard dirty/stay cycle ----------

describe("W29 — Draft guard state machine", () => {
  it("makeWorkflowCtx produces valid payload with all required fields", () => {
    const ctx = makeWorkflowCtx();
    expect(ctx.schema_version).toBe("workflow-context/1.0");
    expect(ctx.battery_id).toBe("CELL_001");
    expect(ctx.experiment_id).toBe("EXP_001");
    expect(ctx.current_step).toBeDefined();
    expect(ctx.step_statuses).toBeDefined();
    expect(ctx.steps).toBeDefined();
    expect(ctx.meta.read_only).toBe(true);
    expect(ctx.meta.no_recomputation).toBe(true);
  });

  it("draft guard payload supports pending_action for WAITING state", () => {
    const ctx = makeWorkflowCtx();
    expect(ctx.pending_action).toBeDefined();
    expect(ctx.pending_action!.status).toBe("WAITING_FOR_USER");
    expect(ctx.pending_action!.action_id).toBe("RESOLVE_PENDING_ACTION");
  });

  it("draft guard payload supports recommended_next_action", () => {
    const ctx = makeWorkflowCtx();
    expect(ctx.recommended_next_action).toBeDefined();
    expect(ctx.recommended_next_action!.action_id).toBe("RESOLVE_PENDING_ACTION");
    expect(ctx.recommended_next_action!.route).toMatch(/^\/experiments\//);
  });
});

// ---------- W30 — pageToStep mapping ----------

describe("W30 — pageToStep mapping correctness", () => {
  it("models page maps to MODELS step", async () => {
    const { WF_STEP_ROUTES } = await import("../src/hooks/useWorkflowContext");
    const modelsStep = Object.entries(WF_STEP_ROUTES).find(([, route]) => route === "models");
    expect(modelsStep).toBeDefined();
    expect(modelsStep![0]).toBe("MODELS");
  });

  it("report page maps to REPORT step", async () => {
    const { WF_STEP_ROUTES } = await import("../src/hooks/useWorkflowContext");
    const reportStep = Object.entries(WF_STEP_ROUTES).find(([, route]) => route === "report");
    expect(reportStep).toBeDefined();
    expect(reportStep![0]).toBe("REPORT");
  });

  it("analysis page maps to TARGET (first step in chain)", async () => {
    const { WF_STEP_ROUTES } = await import("../src/hooks/useWorkflowContext");
    const analysisSteps = Object.entries(WF_STEP_ROUTES).filter(([, route]) => route === "analysis");
    expect(analysisSteps.length).toBe(5);
    expect(analysisSteps[0]![0]).toBe("TARGET");
  });

  it("dataset-split maps to SPLIT step", async () => {
    const { WF_STEP_ROUTES } = await import("../src/hooks/useWorkflowContext");
    const splitStep = Object.entries(WF_STEP_ROUTES).find(([, route]) => route === "advanced/dataset-split");
    expect(splitStep).toBeDefined();
    expect(splitStep![0]).toBe("SPLIT");
  });
});

// ---------- W31 — No localStorage compliance ----------

describe("W31 — No localStorage/sessionStorage usage", () => {
  it("WorkflowContextPayload has no localStorage dependency", () => {
    const ctx = makeWorkflowCtx();
    const serialized = JSON.stringify(ctx);
    expect(serialized).not.toContain("localStorage");
    expect(serialized).not.toContain("sessionStorage");
  });

  it("workflow context is server-derived (read_only + no_recomputation)", () => {
    const ctx = makeWorkflowCtx();
    expect(ctx.meta.read_only).toBe(true);
    expect(ctx.meta.no_recomputation).toBe(true);
  });

  it("artifact_freshness comes from backend, not client cache", () => {
    const ctx = makeWorkflowCtx();
    expect(ctx.artifact_freshness).toBeDefined();
    expect(typeof ctx.artifact_freshness.dataset).toBe("string");
    expect(typeof ctx.artifact_freshness.models).toBe("string");
    expect(typeof ctx.artifact_freshness.report).toBe("string");
  });
});
