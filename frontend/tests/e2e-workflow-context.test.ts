/**
 * BRW-025R-WF — E2E scenarios 1–10 (real FastAPI backend).
 *
 * Tests the workflow-context endpoint and full scientific workflow chain
 * against real CELL_001/EXP_001 artifacts.
 *
 * E2E1  happy path: workflow-context returns complete chain
 * E2E2  navigation immutability: GET-only, no POST side-effects
 * E2E3  deep link: BLOCKED step returns structured blocking (not 404)
 * E2E4  stale chain: artifact_freshness present for dataset/models/report
 * E2E5  WAITING state: pending_action with WAITING_FOR_USER
 * E2E6  impossible split: BLOCKED SPLIT when no dataset
 * E2E7  draft guard: read_only + no_recomputation meta flags
 * E2E8  experiment isolation: different experiments → different contexts
 * E2E9  assistant next action: typed_actions carry route
 * E2E10 navigation immutability: workflow-context is GET-only endpoint
 */
import { resolve } from "node:path";
import { beforeAll, afterAll, describe, expect, it } from "vitest";
import type { Server } from "node:http";

let server: Server | null = null;
const port = 8972;
let available = false;
const api = "/api/v1";

beforeAll(async () => {
  const { spawn } = await import("node:child_process");
  const repo = resolve(new URL(import.meta.url).pathname, "../..");
  const repoRoot = resolve(repo, "..");
  const proc = spawn(
    `${repoRoot}/.venv/bin/uvicorn`,
    ["battery_workbench.api.serve:app", "--port", String(port)],
    { cwd: repoRoot, stdio: "ignore" },
  );
  server = { close: () => proc.kill() } as unknown as Server;
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}${api}/health`);
      if (r.ok) {
        available = true;
        break;
      }
    } catch {
      await new Promise((r) => setTimeout(r, 250));
    }
  }
});

afterAll(() => {
  server?.close();
});

const B = "CELL_001";
const E = "EXP_001";

async function getJson(path: string): Promise<Record<string, unknown>> {
  const r = await fetch(`http://127.0.0.1:${port}${api}${path}`);
  expect(r.ok, `GET ${path} → ${r.status}`).toBe(true);
  return (await r.json()) as Record<string, unknown>;
}

interface WorkflowContext {
  schema_version: string;
  battery_id: string;
  experiment_id: string;
  current_step: string;
  step_statuses: Record<string, string>;
  steps: Record<string, { status: string; committed?: Record<string, unknown>; blocking?: Record<string, string> }>;
  recommended_next_action: { action_id: string; step: string; label: string; route: string } | null;
  pending_action: { action_id: string; status: string; label: string; route: string; scientific_reason: string } | null;
  artifact_freshness: Record<string, string>;
  typed_actions: { action_id: string; label: string; route: string }[];
  meta: { read_only: boolean; no_recomputation: boolean };
}

async function getWorkflowContext(batteryId = B, experimentId = E): Promise<WorkflowContext> {
  const res = await getJson(`/experiments/${batteryId}/${experimentId}/workflow-context`);
  return res.data as WorkflowContext;
}

// ---------- E2E1 — Happy path: full workflow chain ----------

describe("E2E1 — Happy path: workflow-context returns complete chain", () => {
  it("returns schema_version workflow-context/1.0", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    expect(wf.schema_version).toBe("workflow-context/1.0");
  });

  it("returns all 8 step statuses", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    const expectedSteps = ["TARGET", "ALIGNMENT", "FEATURES", "PREVIEW", "DATASET", "SPLIT", "MODELS", "REPORT"];
    for (const step of expectedSteps) {
      expect(wf.step_statuses[step]).toBeDefined();
    }
  });

  it("returns steps with committed scientific identity", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    expect(wf.steps.TARGET).toBeDefined();
    expect(wf.steps.TARGET!.status).toBeDefined();
  });

  it("returns current_step as one of the 8 canonical steps", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    const validSteps = ["TARGET", "ALIGNMENT", "FEATURES", "PREVIEW", "DATASET", "SPLIT", "MODELS", "REPORT"];
    expect(validSteps).toContain(wf.current_step);
  });
});

// ---------- E2E2 — Navigation immutability (GET-only) ----------

describe("E2E2 — Navigation immutability: GET-only, no side-effects", () => {
  it("workflow-context endpoint accepts GET", async (ctx) => {
    if (!available) ctx.skip();
    const r = await fetch(`http://127.0.0.1:${port}${api}/experiments/${B}/${E}/workflow-context`);
    expect(r.ok).toBe(true);
    expect(r.status).toBe(200);
  });

  it("workflow-context endpoint rejects POST (405)", async (ctx) => {
    if (!available) ctx.skip();
    const r = await fetch(`http://127.0.0.1:${port}${api}/experiments/${B}/${E}/workflow-context`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    expect(r.status).toBe(405);
  });

  it("repeated GET returns same data (idempotent read)", async (ctx) => {
    if (!available) ctx.skip();
    const wf1 = await getWorkflowContext();
    const wf2 = await getWorkflowContext();
    expect(wf1.schema_version).toBe(wf2.schema_version);
    expect(wf1.current_step).toBe(wf2.current_step);
    expect(wf1.step_statuses).toEqual(wf2.step_statuses);
  });
});

// ---------- E2E3 — Deep link: BLOCKED step returns structured blocking ----------

describe("E2E3 — Deep link: structured blocking for BLOCKED steps", () => {
  it("BLOCKED step has blocking sub-object with required fields", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    const blockedSteps = Object.entries(wf.steps).filter(([, v]) => v.status === "BLOCKED");
    for (const [key, step] of blockedSteps) {
      expect(step.blocking, `Step ${key} should have blocking`).toBeDefined();
      if (step.blocking) {
        expect(step.blocking.blocking_code).toBeDefined();
        expect(step.blocking.blocking_message).toBeDefined();
        expect(step.blocking.required_action).toBeDefined();
        expect(step.blocking.scientific_reason).toBeDefined();
      }
    }
  });

  it("non-BLOCKED steps may expose prerequisite blockers with structured recovery actions", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    const nonBlocked = Object.entries(wf.steps).filter(([, v]) => v.status !== "BLOCKED");
    for (const [, step] of nonBlocked) {
      if (step.blocking) {
        expect(step.blocking.blocking_code).toBeDefined();
        expect(step.blocking.blocking_message).toBeDefined();
        expect(step.blocking.required_action).toBeDefined();
        expect(step.blocking.scientific_reason).toBeDefined();
      }
    }
  });
});

// ---------- E2E4 — Stale chain: artifact_freshness ----------

describe("E2E4 — Stale chain: artifact_freshness present", () => {
  it("artifact_freshness contains dataset/models/report keys", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    expect(wf.artifact_freshness).toBeDefined();
    expect(wf.artifact_freshness.dataset).toBeDefined();
    expect(wf.artifact_freshness.models).toBeDefined();
    expect(wf.artifact_freshness.report).toBeDefined();
  });

  it("freshness values are valid vocabulary", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    const validFreshness = ["CURRENT", "STALE", "LEGACY", "SUPERSEDED", "MISSING"];
    for (const val of Object.values(wf.artifact_freshness)) {
      expect(validFreshness).toContain(val);
    }
  });
});

// ---------- E2E5 — WAITING state: pending_action ----------

describe("E2E5 — WAITING state: pending_action structure", () => {
  it("pending_action is null or has WAITING_FOR_USER status", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    if (wf.pending_action) {
      expect(wf.pending_action.status).toBe("WAITING_FOR_USER");
      expect(wf.pending_action.action_id).toBeDefined();
      expect(wf.pending_action.label).toBeDefined();
      expect(wf.pending_action.route).toBeDefined();
    }
  });

  it("recommended_next_action has action_id + route", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    if (wf.recommended_next_action) {
      expect(wf.recommended_next_action.action_id).toBeDefined();
      expect(wf.recommended_next_action.route).toMatch(/^\/experiments\//);
      expect(wf.recommended_next_action.label).toBeDefined();
    }
  });
});

// ---------- E2E6 — Impossible split: BLOCKED when no dataset ----------

describe("E2E6 — Impossible split: SPLIT BLOCKED when no dataset", () => {
  it("SPLIT status is consistent with DATASET status", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    const datasetStatus = wf.step_statuses.DATASET;
    const splitStatus = wf.step_statuses.SPLIT;
    if (datasetStatus === "NOT_STARTED" || datasetStatus === "BLOCKED") {
      expect(splitStatus === "BLOCKED" || splitStatus === "NOT_STARTED").toBe(true);
    }
  });

  it("when SPLIT is BLOCKED, blocking explains dataset dependency", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    if (wf.step_statuses.SPLIT === "BLOCKED") {
      const splitStep = wf.steps.SPLIT!;
      expect(splitStep.blocking).toBeDefined();
      expect(splitStep.blocking!.blocking_message).toBeDefined();
    }
  });
});

// ---------- E2E7 — Draft guard: read_only + no_recomputation ----------

describe("E2E7 — Draft guard: meta flags", () => {
  it("meta.read_only is true (no writes)", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    expect(wf.meta.read_only).toBe(true);
  });

  it("meta.no_recomputation is true (no science recomputed)", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    expect(wf.meta.no_recomputation).toBe(true);
  });
});

// ---------- E2E8 — Experiment isolation ----------

describe("E2E8 — Experiment isolation: different experiments → different contexts", () => {
  it("workflow-context returns correct battery_id/experiment_id", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    expect(wf.battery_id).toBe(B);
    expect(wf.experiment_id).toBe(E);
  });

  it("invalid experiment returns 404 (not leaked data)", async (ctx) => {
    if (!available) ctx.skip();
    const r = await fetch(`http://127.0.0.1:${port}${api}/experiments/INVALID_CELL/INVALID_EXP/workflow-context`);
    expect(r.status).toBe(404);
  });
});

// ---------- E2E9 — Assistant next action: typed_actions ----------

describe("E2E9 — Assistant next action: typed_actions carry route", () => {
  it("typed_actions array contains action_id + route", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    expect(Array.isArray(wf.typed_actions)).toBe(true);
    for (const action of wf.typed_actions) {
      expect(action.action_id).toBeDefined();
      expect(action.label).toBeDefined();
      expect(action.route).toMatch(/^\/experiments\//);
    }
  });

  it("typed_actions routes are valid workflow routes", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    const validRouteSuffixes = ["overview", "analysis", "models", "report", "advanced/dataset-split", "dataset-split", "waveform"];
    for (const action of wf.typed_actions) {
      const suffix = action.route.replace(/^\/experiments\/[^/]+\/[^/]+\//, "");
      expect(validRouteSuffixes).toContain(suffix);
    }
  });
});

// ---------- E2E10 — Navigation artifact immutability ----------

describe("E2E10 — Navigation artifact immutability", () => {
  it("workflow-context response has no write tokens or mutation URLs", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    const serialized = JSON.stringify(wf);
    expect(serialized).not.toContain("POST");
    expect(serialized).not.toContain("DELETE");
    expect(serialized).not.toContain("mutation_url");
  });

  it("step statuses are read-only snapshot (no edit_url fields)", async (ctx) => {
    if (!available) ctx.skip();
    const wf = await getWorkflowContext();
    for (const step of Object.values(wf.steps)) {
      expect(step).not.toHaveProperty("edit_url");
      expect(step).not.toHaveProperty("mutation_url");
    }
  });
});
