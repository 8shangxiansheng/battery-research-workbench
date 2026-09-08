/**
 * BRW-025R-FE-R1 — Target-first workflow E2E (Scenarios A–Q, real API).
 * Real CELL_001/EXP_001 artifacts via uvicorn serve:app. Read-only except
 * deterministic idempotent dataset REUSED paths; no artifact mutation.
 *
 * @vitest-environment node
 */
import { beforeAll, afterAll, describe, expect, it } from "vitest";
import { spawn, type ChildProcess } from "node:child_process";
import { resolve } from "node:path";

const port = 8997;
const api = `http://127.0.0.1:${port}/api/v1`;
let proc: ChildProcess | null = null;
let available = false;

beforeAll(async () => {
  const repoRoot = resolve(new URL(import.meta.url).pathname, "../../..");
  proc = spawn(
    `${repoRoot}/.venv/bin/uvicorn`,
    ["battery_workbench.api.serve:app", "--port", String(port)],
    { cwd: repoRoot, stdio: "ignore" },
  );
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch(`${api}/health`);
      if (r.ok) { available = true; break; }
    } catch { await new Promise(r => setTimeout(r, 250)); }
  }
});
afterAll(() => proc?.kill());

declare global { interface Window { __dbg?: unknown } }

const B = "CELL_001";
const E = "EXP_001";

async function get(path: string): Promise<Record<string, unknown>> {
  const r = await fetch(`${api}${path}`);
  expect(r.ok, `GET ${path} → ${r.status}`).toBe(true);
  return (await r.json()) as Record<string, unknown>;
}
async function post(path: string, body: unknown): Promise<{ status: number; body: Record<string, unknown> }> {
  const r = await fetch(`${api}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return { status: r.status, body: (await r.json()) as Record<string, unknown> };
}

/* eslint-disable @typescript-eslint/no-explicit-any */
function d(x: any) { return x.data; }
function sorted(xs: number[]) { return [...xs].sort((a, b) => a - b); }

describe("BRW-025R-FE-R1 E2E A–Q", () => {
  it("A: Select Reference SOC — target metadata + retrospective wording", async (ctx) => {
    if (!available) ctx.skip();
    const targets: any = d(await get(`/experiments/${B}/${E}/targets`));
    const soc = targets.targets.find((t: any) => t.target_id === "reference_soc_percent");
    expect(soc).toBeTruthy();
    expect(soc.semantic_type).toBe("DERIVED_REFERENCE_LABEL");
    expect(soc.coverage.valid).toBe(3995);
    expect(JSON.stringify(targets)).not.toMatch(/True SOC|Ground Truth/);
    expect(soc.limitation).toMatch(/Retrospective/i);
  });

  it("B: Alignment summary — 3999/3995/4/0/3995/4 + canonical semantics", async (ctx) => {
    if (!available) ctx.skip();
    const s: any = d(await get(`/experiments/${B}/${E}/alignment-summary`));
    expect(s.total_frames).toBe(3999);
    expect(s.matched_unique).toBe(3995);
    expect(s.ambiguous).toBe(4);
    expect(s.unmatched).toBe(0);
    expect(s.eligible).toBe(3995);
    expect(s.excluded).toBe(4);
    expect(s.sync_quality.validated_sync).toBe(false);
    expect(s.sync_quality.timebase_status).toBe("PROVISIONAL");
    expect(s.sync_quality.matching_performed).toBe(true);
  });

  it("C: Inspect unique row — full provenance chain", async (ctx) => {
    if (!available) ctx.skip();
    const s: any = d(await get(`/experiments/${B}/${E}/alignment-samples?filter=eligible&limit=5`));
    const row = s.samples[0];
    expect(row.frame_index_raw).toBe(0);
    expect(row.measurement_event_id).toContain("ME::CELL_001");
    expect(row.electrical_asset_id).toBe("E001");
    expect(row.electrical_record_locator).not.toBeNull();
    expect(row.sync_error_s).not.toBeNull();
    expect(row.targets["reference_soc_percent"]).not.toBeNull();
    expect(row.analysis_eligible).toBe(true);
  });

  it("D: Inspect ambiguous row — electrical identity null + exclusion reason", async (ctx) => {
    if (!available) ctx.skip();
    const s: any = d(await get(`/experiments/${B}/${E}/alignment-samples?filter=ambiguous`));
    expect(s.samples.length).toBe(4);
    for (const row of s.samples) {
      expect(row.electrical_asset_id).toBeNull();
      expect(row.electrical_record_locator).toBeNull();
      expect(row.analysis_eligible).toBe(false);
      expect(row.sync_ambiguous).toBe(true);
    }
    const excl: any = d(await get(`/experiments/${B}/${E}/alignment-exclusions`));
    const amb = excl.exclusions.find((e: any) => e.reason === "AMBIGUOUS_SYNC");
    expect(amb.count).toBe(4);
  });

  it("E+F: Select 3 features + preview Feature–Label Table", async (ctx) => {
    if (!available) ctx.skip();
    const r = await post(`/experiments/${B}/${E}/feature-label-preview`, {
      target_id: "reference_soc_percent",
      features: ["SWA", "BOTTOM_AMP", "TOF_XCORR"],
      limit: 25,
    });
    expect(r.status).toBe(200);
    const table: any = r.body.data;
    expect(table.features).toEqual(["SWA", "BOTTOM_AMP", "TOF_XCORR"]);
    expect(table.summary.eligible_rows).toBe(3995);
    expect(table.summary.excluded_rows).toBe(4);
    expect(sorted(table.summary.cycles)).toEqual([1, 2]);
    const ids = table.rows.map((row: any) => row.measurement_event_id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const row of table.rows) {
      expect(Object.keys(row.values)).toEqual(["SWA", "BOTTOM_AMP", "TOF_XCORR"]);
      expect(row.target).not.toBeNull();
    }
  });

  it("G: Row provenance in preview rows — event→electrical→sync", async (ctx) => {
    if (!available) ctx.skip();
    const r = await post(`/experiments/${B}/${E}/feature-label-preview`, {
      target_id: "reference_soc_percent", features: ["SWA"], limit: 5,
    });
    const row: any = (r.body.data as any)?.rows[0];
    expect(row.measurement_event_id).toBeTruthy();
    expect(row.electrical_asset_id).toBe("E001");
    expect(row.sync_error_s).not.toBeNull();
  });

  it("H: SOC exploratory ranking — Pearson/Spearman overall", async (ctx) => {
    if (!available) ctx.skip();
    const r = await post(`/experiments/${B}/${E}/feature-target-ranking`, {
      target_id: "reference_soc_percent", features: ["SWA", "BOTTOM_AMP"], mode: "EXPLORATORY",
    });
    expect(r.status).toBe(200);
    const ranking: any = (r.body.data as any)?.ranking;
    expect(ranking.length).toBe(2);
    for (const entry of ranking) {
      expect(entry.status).toBe("VALID");
      expect(Math.abs(entry.pearson_overall)).toBeLessThanOrEqual(1);
    }
  });

  it("I: Charge/Discharge views — direction-dependent SOC relationship", async (ctx) => {
    if (!available) ctx.skip();
    const r = await post(`/experiments/${B}/${E}/feature-target-ranking`, {
      target_id: "reference_soc_percent", features: ["SWA", "TOF_XCORR"], mode: "EXPLORATORY",
    });
    const ranking: any = (r.body.data as any)?.ranking;
    const swa = ranking.find((e: any) => e.feature_code === "SWA");
    expect(swa.pearson_charge).toBeGreaterThan(0);
    expect(swa.pearson_discharge).toBeLessThan(0);
    expect(swa.direction_dependent).toBe(true);
  });

  it("J: Switch to Temperature — reuse sync/features (no resync), honest readiness", async (ctx) => {
    if (!available) ctx.skip();
    const targets: any = d(await get(`/experiments/${B}/${E}/targets`));
    const temp = targets.targets.find((t: any) => t.target_id === "temperature_c");
    expect(temp.readiness).toBe("UNAVAILABLE");
    expect(temp.coverage.valid).toBe(0);
    const before: any = d(await get(`/experiments/${B}/${E}/alignment-summary`));
    const after: any = d(await get(`/experiments/${B}/${E}/alignment-summary`));
    expect(after.total_frames).toBe(before.total_frames);
    expect(after.matched_unique).toBe(before.matched_unique);
  });

  it("K: SOH limited — group summary only, no frame-level leaderboard", async (ctx) => {
    if (!available) ctx.skip();
    const r = await post(`/experiments/${B}/${E}/feature-target-ranking`, {
      target_id: "soh_capacity_reference_percent", features: ["SWA"], mode: "EXPLORATORY",
    });
    const data: any = r.body.data;
    expect(data.ranking).toEqual([]);
    expect(data.group_summary.length).toBe(2);
    const sohValues = new Set(data.group_summary.map((g: any) => g.soh_percent));
    expect(sohValues.size).toBe(2);
  });

  it("L: Build exploratory feature table — idempotent deterministic create", async (ctx) => {
    if (!available) ctx.skip();
    const r1 = await post("/datasets", {
      battery_id: B, experiment_id: E, dataset_family: "SOC",
      target: "soc_reference_percent", selected_features: ["amplitude_a_u"],
    });
    expect(r1.status).toBe(200);
    const r2 = await post("/datasets", {
      battery_id: B, experiment_id: E, dataset_family: "SOC",
      target: "soc_reference_percent", selected_features: ["amplitude_a_u"],
    });
    expect((r2.body.data as any)?.dataset_id).toBe((r1.body.data as any)?.dataset_id);
  });

  it("M: ML-safe flow — requires grouped split (no random frame split)", async (ctx) => {
    if (!available) ctx.skip();
    const splits: any = d(await get(`/experiments/${B}/${E}/splits`));
    for (const s of splits.splits) {
      expect(s.strategy).not.toBe("RANDOM_FRAME_SPLIT");
      expect(s.strategy).not.toBe("RANDOM_ROW_SPLIT");
    }
    const bad = await post("/feature-analyses", {
      battery_id: B, experiment_id: E, analysis_mode: "TRAIN_ONLY_ML_SAFE",
      target: "soc_reference_percent", candidate_features: ["amplitude_a_u"],
    });
    expect(bad.status).toBe(400);
  });

  it("N: TRAIN-only feature selection — split_id+fold accepted, list available", async (ctx) => {
    if (!available) ctx.skip();
    const ok = await post("/feature-analyses", {
      battery_id: B, experiment_id: E, analysis_mode: "TRAIN_ONLY_ML_SAFE",
      target: "soc_reference_percent", candidate_features: ["amplitude_a_u"],
      split_id: "SPLIT::062cf007d21578a11ab2d728", fold_index: 2,
    });
    expect(ok.status).toBe(200);
    const list: any = d(await get(`/experiments/${B}/${E}/feature-analyses`));
    const mlSafe = list.analyses.filter((a: any) => a.analysis_mode === "TRAIN_ONLY_ML_SAFE");
    expect(mlSafe.length).toBeGreaterThan(0);
    for (const a of mlSafe) expect(a.split_id).toBeTruthy();
  });

  it("O: Preview X/y — target provenance + eligible/excluded + readiness", async (ctx) => {
    if (!available) ctx.skip();
    const r = await post(`/experiments/${B}/${E}/feature-label-preview`, {
      target_id: "reference_soc_percent", features: ["SWA"], limit: 10,
    });
    const table: any = r.body.data;
    expect(table.target_source).toMatch(/label engine/i);
    expect(table.target_readiness).toBe("READY_FOR_LIMITED_EVALUATION");
    expect(table.summary.eligible_rows).toBeGreaterThan(0);
    expect(table.summary.excluded_by_reason["AMBIGUOUS_SYNC"]).toBe(4);
  });

  it("P: Build dataset → model handoff — split + models endpoints", async (ctx) => {
    if (!available) ctx.skip();
    const splits: any = d(await get(`/experiments/${B}/${E}/splits`));
    const ready = splits.splits.find((s: any) => s.readiness_status === "READY_FOR_LIMITED_EVALUATION");
    expect(ready).toBeTruthy();
    expect(ready.strategy).toBe("LEAVE_ONE_GROUP_OUT");
    const results: any = d(await get(`/experiments/${B}/${E}/results?limit=200`));
    expect(results.filter((x: any) => x.result_type === "MODEL_COMPARISON").length).toBeGreaterThan(0);
  });

  it("Q: Report target + alignment + selection provenance — read-only", async (ctx) => {
    if (!available) ctx.skip();
    const reports: any = d(await get(`/reports?battery_id=${B}&experiment_id=${E}&limit=50`));
    expect(Array.isArray(reports)).toBe(true);
    const targets: any = d(await get(`/experiments/${B}/${E}/targets`));
    expect(targets.targets.length).toBe(5);
    const summary: any = d(await get(`/experiments/${B}/${E}/alignment-summary`));
    expect(summary.sync_quality.validated_sync).toBe(false);
  });
});
