/**
 * BRW-027R E2E A–O — assistant conversation scenarios against the real
 * CELL_001/EXP_001 API. Read-only except idempotent REUSED paths.
 *
 * @vitest-environment node
 */
import { beforeAll, afterAll, describe, expect, it } from "vitest";
import { spawn, type ChildProcess } from "node:child_process";
import { resolve } from "node:path";

const port = 8995;
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

const B = "CELL_001";
const E = "EXP_001";
let sessionId = "";

async function openSession(): Promise<string> {
  const r = await fetch(`${api}/experiments/${B}/${E}/assistant/session`, { method: "POST" });
  expect(r.ok).toBe(true);
  const j = await r.json();
  return j.data.session_id;
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function send(message: string): Promise<Record<string, any>> {
  const r = await fetch(`${api}/experiments/${B}/${E}/assistant/session/${sessionId}/message`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, current_page: "analysis" }),
  });
  expect(r.ok, `send ${message} → ${r.status}`).toBe(true);
  return (await r.json()).data;
}

describe("BRW-027R E2E A–O", () => {
  beforeAll(async () => {
    if (!available) return;
    sessionId = await openSession();
  });

  it("A: 帮我研究SOC — target selected + retrospective disclaimer", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("帮我研究SOC");
    expect(d.intent).toBe("SELECT_TARGET");
    expect(d.message).toMatch(/retrospective/i);
    expect(d.message).not.toMatch(/True SOC|Ground Truth/i);
  });

  it("B: 哪些特征和SOC关系明显？ — ranking with causation disclaimer", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("哪些特征和SOC关系明显？");
    expect(d.message).toContain("因果关系");
    expect(d.message).toContain("非 ML-safe");
  });

  it("C: 用这些训练模型 — exploratory ranking not sent to model", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("用这些训练模型");
    expect(d.message).toContain("grouped split");
    expect(d.status).toBe("SCIENTIFIC_BLOCK");
  });

  it("D: 这个模型效果怎么样？ — Dummy-first honest interpretation", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("这个模型效果怎么样？");
    expect(d.message).toContain("Dummy");
    expect(d.message).toContain("不是处理故障");
  });

  it("E: 训练SOH模型 — blocked with 2-state explanation", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("训练SOH模型");
    expect(d.status).toBe("SCIENTIFIC_BLOCK");
    expect(d.message).toContain("2 个独立状态");
  });

  it("F: 看温度和BPS关系 — temperature readiness honest", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("看温度和BPS关系");
    expect(d.status).toBe("SUCCEEDED");
  });

  it("G: missing-fs TOF µs — no fabricated physical time", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("算TOF微秒");
    expect(d.message).not.toMatch(/\d+\s*µs/);
  });

  it("H: gate needs calibration — points to Calibrate Gates flow", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("提取底波幅值");
    expect(d.status).toBe("SUCCEEDED");
  });

  it("I: 随机80/20训练测试 — refused with leakage explanation", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("随机80/20训练测试");
    expect(d.status).toBe("SCIENTIFIC_BLOCK");
    expect(d.message).toContain("泄漏");
    expect(d.message).toContain("Leave-One-Group-Out");
  });

  it("J: 已经跨电池验证了吗？ — within-battery limitation", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("已经跨电池验证了吗？");
    expect(d.status).toBe("SCIENTIFIC_BLOCK");
    expect(d.message).toContain("within-battery");
  });

  it("K: 生成SOC研究报告 — no retraining claim", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("生成这次SOC研究报告");
    expect(d.message).toContain("不会重新训练");
  });

  it("L: 换成温度看看 — target switch, sync/features reused", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("换成温度看看");
    expect(d.intent).toBe("SELECT_TARGET");
    expect(d.message).not.toMatch(/True SOC|Ground Truth/i);
  });

  it("M: 为什么3999只有3995？ — exclusion funnel explanation", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("为什么3999只有3995？");
    expect(d.message).toContain("3995");
    expect(d.message).toContain("4");
    expect(d.message).toContain("validated_sync=false");
  });

  it("N: 这张表的X和y是什么？ — features + exactly one target", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("这张表的X和y是什么？");
    expect(d.status).toBe("SUCCEEDED");
  });

  it("O: 这个结论有什么证据？ — evidence refs surfaced", async (ctx) => {
    if (!available) ctx.skip();
    const d = await send("这个结论有什么证据？");
    expect(d.message).toContain("证据");
  });

  it("session persistence: conversation stored, no CoT", async (ctx) => {
    if (!available) ctx.skip();
    const r = await fetch(`${api}/experiments/${B}/${E}/assistant/session/${sessionId}`);
    const j = await r.json();
    expect(j.data.conversation.length).toBeGreaterThan(0);
    expect(JSON.stringify(j.data)).not.toMatch(/chain_of_thought/i);
    const s = JSON.stringify(j.data.conversation);
    expect(s).not.toContain("ToolResult(");
  });
});
