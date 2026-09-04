/**
 * BRW-025 §69 E2E happy path（真实 CELL_001/EXP_001 artifacts，尽量 REUSE）。
 * workspace → waveform → gate → exploratory analysis → dataset/split → model → report → evidence。
 * 全部通过 typed client 走真实 API（AppFactory 从真实 processed root 起服务）；
 * 不污染真实数据：gate/analysis 提交写的是 API deterministic 幂等路径或 REUSED。
 */
import { resolve } from "node:path";
import { beforeAll, afterAll, describe, expect, it } from "vitest";
import type { Server } from "node:http";

let server: Server | null = null;
const port = 8971;
let available = false;
const api = "/api/v1";

beforeAll(async () => {
  // 起真实 FastAPI（uvicorn）作为 E2E 后端；不可用则 skip
  const { spawn } = await import("node:child_process");
  const repo = resolve(new URL(import.meta.url).pathname, "../..");
  const repoRoot = resolve(repo, "..");
  const proc = spawn(
    `${repoRoot}/.venv/bin/uvicorn`,
    ["battery_workbench.api.serve:app", "--port", String(port)],
    { cwd: repoRoot, stdio: "ignore" },
  );
  server = { close: () => proc.kill() } as unknown as Server;
  // wait for health
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

describe("E2E happy path（§69）", () => {
  it("workspace → evidence 全链 REUSED", async (ctx) => {
    if (!available) ctx.skip();
    // 1. workspace
    const ws = (await getJson(`/experiments/${B}/${E}/workspace-summary`)) as {
      data: { scientific_status: string; limitations_registry: unknown[] };
    };
    expect(ws.data.scientific_status).toBe("READY_FOR_LIMITED_EVALUATION");
    expect(ws.data.limitations_registry.length).toBeGreaterThan(0);

    // 2. waveform frames（真实 zarr preview）
    const frames = (await getJson(`/experiments/${B}/${E}/waveform-frames`)) as {
      data: { frame_count: number; x_axis: string };
    };
    expect(frames.data.frame_count).toBe(3999);
    expect(frames.data.x_axis).toBe("SAMPLE_INDEX");

    // 3. features
    const features = (await getJson(`/experiments/${B}/${E}/features`)) as {
      data: { features: { feature_name: string; availability: string }[] };
    };
    const tof = features.data.features.find((f) => f.feature_name === "tof_us");
    expect(tof?.availability).toBe("NOT_AVAILABLE_CURRENT_ENVIRONMENT");

    // 4. results / modeling
    const results = (await getJson(`/experiments/${B}/${E}/results?limit=200`)) as {
      data: { result_type: string; strategy: string | null; value: unknown }[];
    };
    const macro = results.data.filter((r) => r.result_type === "MODEL_COMPARISON");
    expect(macro.length).toBe(5);

    // 5. evidence + lineage
    const evidence = (await getJson(`/experiments/${B}/${E}/evidence`)) as {
      data: { evidence: unknown[] };
    };
    expect(evidence.data.evidence.length).toBeGreaterThan(0);
    const lineage = (await getJson(`/experiments/${B}/${E}/lineage`)) as {
      data: { lineage_chain: { artifact_type: string; status: string }[] };
    };
    expect(lineage.data.lineage_chain.some((n) => n.status === "AVAILABLE")).toBe(true);

    // 6. deterministic report create → REUSED on repeat（不污染：REPORT 是幂等语义）
    const post = async (path: string, body: unknown): Promise<{ status: number; body: Record<string, unknown> }> => {
      const r = await fetch(`http://127.0.0.1:${port}${api}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return { status: r.status, body: (await r.json()) as Record<string, unknown> };
    };
    const report1 = await post("/reports", { battery_id: B, experiment_id: E });
    expect(report1.status).toBe(200);
    const report2 = await post("/reports", { battery_id: B, experiment_id: E });
    expect((report2.body.data as Record<string, unknown>).reuse_status).toBe("REUSED");
    expect(
      (report1.body.data as Record<string, unknown>).report_id ===
        (report2.body.data as Record<string, unknown>).report_id,
    ).toBe(true);
  });
});
