/** BRW-017R2 视觉验收 — canonical envelope-peak TOF（2 张 1440×900）。
 *  前置：API :8000 + UI :5173 已启动。
 *  运行：cd frontend && node screenshot-canonical-tof.mjs
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = "http://localhost:5173";
const OUT = "../docs/ui/screenshots";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const exp = "/experiments/CELL_001/EXP_001";
const results = [];

async function shot(id, url, { wait = 2500, extra } = {}) {
  await page.goto(BASE + url, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(wait);
  let ok = true;
  if (extra) { try { await extra(); } catch (e) { ok = false; console.error("✗", id, String(e).slice(0, 140)); } }
  await page.screenshot({ path: `${OUT}/${id}.png` });
  results.push({ id, ok });
  console.log(ok ? "✓" : "×", id);
}

// 01 canonical TOF panel on the waveform page
await shot("01_canonical_tof_panel", `${exp}/waveform`, {
  expectVisible: undefined,
  extra: async () => {
    await page.getByTestId("canonical-tof-panel").waitFor({ state: "visible", timeout: 15000 });
    await page.getByTestId("canonical-tof-panel").scrollIntoViewIfNeeded();
    await page.waitForTimeout(800);
  },
});

// 02 agent 算TOF — canonical method answer
await shot("02_canonical_tof_agent", `${exp}/waveform`, {
  extra: async () => {
    await page.getByRole("button", { name: /Research Assistant/i }).first().click();
    await page.getByTestId("assistant-drawer").waitFor({ state: "visible", timeout: 15000 });
    await page.getByTestId("assistant-input").fill("算TOF");
    await page.getByTestId("assistant-send").click();
    await page.getByTestId("assistant-answer").first().waitFor({ state: "visible", timeout: 15000 });
    await page.waitForTimeout(600);
  },
});

writeFileSync("../docs/ui/screenshots/canonical-tof-results.json", JSON.stringify(results, null, 2));
const passed = results.filter(r => r.ok).length;
console.log(`BRW-017R2 视觉验收完成 → ${OUT}（${passed}/${results.length}）`);
if (passed !== results.length) process.exit(1);
await browser.close();
