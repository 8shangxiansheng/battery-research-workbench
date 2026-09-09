/** BRW-028 final acceptance — 16 screenshots @1440×900 (manifest §29).
 *  前置：API :8000 + UI :5173。断言目标 data-testid 可见，不可见 FAIL。
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = "http://localhost:5173";
const OUT = "../docs/ui/screenshots/final";
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const exp = "/experiments/CELL_001/EXP_001";
const results = [];

async function shot(id, url, { wait = 3000, expectVisible = [], extra } = {}) {
  await page.goto(BASE + url, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(wait);
  let ok = true;
  for (const sel of expectVisible) {
    try { await page.locator(sel).first().waitFor({ state: "visible", timeout: 15000 }); }
    catch { ok = false; console.error("✗", id, "— missing:", sel); break; }
  }
  if (ok && extra) { try { await extra(); } catch (e) { ok = false; console.error("✗", id, String(e).slice(0, 120)); } }
  await page.screenshot({ path: `${OUT}/${id}.png` });
  results.push({ id, ok });
  console.log(ok ? "✓" : "×", id);
}

await shot("01_overview_real_experiment", `${exp}/overview`, {
  // the Research Assistant drawer mounts only when opened — click the trigger
  extra: async () => {
    await page.getByLabel("Research Assistant").click();
    await page.locator("[data-testid=assistant-drawer]").waitFor({ state: "visible", timeout: 15000 });
  },
});
await shot("02_waveform_gates", `${exp}/waveform`, {
  expectVisible: ["[data-testid=physical-features]", "[data-testid=calibrate-gates]"],
  extra: async () => { await page.getByTestId("physical-features").scrollIntoViewIfNeeded(); },
});
await shot("03_target_reference_soc", `${exp}/analysis`, {
  expectVisible: ["[data-testid=target-card-reference_soc_percent]"],
  extra: async () => { await page.getByTestId("target-card-reference_soc_percent").scrollIntoViewIfNeeded(); },
});
await shot("04_alignment_summary", `${exp}/analysis`, {
  extra: async () => {
    await page.getByTestId("select-target-reference_soc_percent").click();
    await page.getByTestId("to-alignment").click();
    await page.getByTestId("alignment-summary").waitFor({ state: "visible", timeout: 20000 });
  },
});
await shot("05_feature_label_table", `${exp}/analysis`, {
  extra: async () => {
    await page.getByTestId("select-target-reference_soc_percent").click();
    await page.getByTestId("to-alignment").click();
    await page.waitForTimeout(1000);
    await page.getByTestId("to-features").click();
    await page.waitForTimeout(800);
    for (const f of ["SWA", "BOTTOM_AMP", "TOF_XCORR"]) {
      await page.getByTestId(`quick-${f}`).click().catch(() => {});
      await page.waitForTimeout(250);
    }
    await page.getByTestId("to-relationships").click();
    await page.waitForTimeout(500);
    await page.getByTestId("to-selection").click();
    await page.waitForTimeout(400);
    await page.getByTestId("to-dataset").click();
    await page.waitForTimeout(2500);
    await page.getByTestId("preview-table-btn").click();
    await page.locator('[data-testid^="fl-row-"]').first().waitFor({ state: "visible", timeout: 30000 });
  },
});
await shot("06_soc_charge_discharge", `${exp}/analysis`, {
  extra: async () => {
    await page.getByTestId("select-target-reference_soc_percent").click();
    await page.getByTestId("to-alignment").click();
    await page.waitForTimeout(1000);
    await page.getByTestId("to-features").click();
    await page.waitForTimeout(800);
    await page.getByTestId("quick-SWA").click();
    await page.getByTestId("quick-BOTTOM_AMP").click();
    await page.getByTestId("to-relationships").click();
    await page.getByTestId("run-ranking-btn").click();
    await page.locator('[data-testid^="rank-"]').first().waitFor({ state: "visible", timeout: 60000 });
  },
});
await shot("07_ml_safe_selection", `${exp}/analysis`, {
  extra: async () => {
    await page.getByTestId("select-target-reference_soc_percent").click();
    await page.getByTestId("to-alignment").click();
    await page.waitForTimeout(900);
    await page.getByTestId("to-features").click();
    await page.waitForTimeout(700);
    await page.getByTestId("quick-SWA").click();
    await page.getByTestId("to-relationships").click();
    await page.waitForTimeout(400);
    await page.getByTestId("to-selection").click();
    await page.getByTestId("mode-mlsafe").click();
    await page.waitForTimeout(1200);
  },
});
await shot("08_dataset_xy", `${exp}/analysis`, {
  extra: async () => {
    await page.getByTestId("select-target-reference_soc_percent").click();
    await page.getByTestId("to-alignment").click();
    await page.waitForTimeout(900);
    await page.getByTestId("to-features").click();
    await page.waitForTimeout(700);
    await page.getByTestId("quick-SWA").click();
    await page.getByTestId("to-relationships").click();
    await page.waitForTimeout(400);
    await page.getByTestId("to-selection").click();
    await page.getByTestId("mode-exploratory").click();
    await page.waitForTimeout(400);
    await page.getByTestId("to-dataset").click();
    await page.waitForTimeout(2500);
    await page.getByTestId("preview-table-btn").click();
    await page.locator('[data-testid^="fl-row-"]').first().waitFor({ state: "visible", timeout: 30000 });
    await page.getByTestId("build-exploratory-btn").click();
    await page.getByTestId("dataset-xy-preview").waitFor({ state: "visible", timeout: 10000 });
    await page.waitForTimeout(400);
  },
});
await shot("09_grouped_split", `${exp}/advanced/dataset-split`, {
  wait: 3500,
});
await shot("10_model_dummy_comparison", `${exp}/models`, { wait: 3500 });
await shot("11_agent_soc_research", `${exp}/analysis`, {
  extra: async () => {
    await page.getByRole("button", { name: /Research Assistant/i }).first().click();
    await page.getByTestId("assistant-drawer").waitFor({ state: "visible", timeout: 15000 });
    await page.waitForTimeout(1500);
    await page.getByTestId("assistant-input").fill("帮我研究SOC");
    await page.getByTestId("assistant-send").click();
    await page.waitForTimeout(4000);
  },
});
await shot("12_agent_soh_block", `${exp}/analysis`, {
  extra: async () => {
    await page.getByRole("button", { name: /Research Assistant/i }).first().click();
    await page.getByTestId("assistant-drawer").waitFor({ state: "visible", timeout: 15000 });
    await page.waitForTimeout(1200);
    await page.getByTestId("assistant-input").fill("训练SOH模型");
    await page.getByTestId("assistant-send").click();
    await page.locator("[data-testid=assistant-block]").first().waitFor({ state: "visible", timeout: 10000 });
    await page.waitForTimeout(400);
  },
});
await shot("13_report_findings", `${exp}/report`, { wait: 3500 });
await shot("14_report_evidence", `${exp}/report`, {
  extra: async () => {
    await page.getByTestId("selected-features").scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(400);
  },
});
await shot("15_reproducibility_manifest", `${exp}/advanced/artifacts`, { wait: 3000 });
await shot("16_full_workbench", `${exp}/overview`, { wait: 2500 });

await browser.close();
const failed = results.filter(r => !r.ok);
writeFileSync("/tmp/final-screenshot-results.json", JSON.stringify(results, null, 2));
console.log(`\nBRW-028 视觉验收完成 → ${OUT}（${results.length - failed.length}/${results.length}）`);
if (failed.length) { console.error("FAILED:", failed.map(f => f.id).join(", ")); process.exit(1); }
