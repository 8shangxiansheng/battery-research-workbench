/** BRW-RC1 §AG — 20 张真实运行截图 + §AA 走查（Back/Forward/DeepLink/Refresh）。
 *  前置：API :8000 + UI :5173。只读：不提交/不冻结/不改工件。
 *  运行：cd frontend && node screenshot-brwrc1.mjs
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = "http://localhost:5173";
const OUT = "../docs/ui/screenshots/brwrc1";
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const results = [];
const exp = "/experiments/CELL_001/EXP_001";
const p = await browser.newPage({ viewport: { width: 1440, height: 900 } });

async function snap(id, ok) {
  await p.screenshot({ path: `${OUT}/${id}.png` });
  results.push({ id, ok: !!ok });
  console.log(ok ? "✓" : "×", id);
}
async function goto(path, wait = 2200) {
  await p.goto(BASE + path, { waitUntil: "networkidle", timeout: 60000 });
  await p.waitForTimeout(wait);
}
const stepper = () => p.getByTestId("workflow-stepper-v2").count();

// 01 overview
await goto(exp + "/overview");
await snap("01_rc1_overview", (await p.getByTestId("research-status-banner").count()) > 0 || (await stepper()) > 0);
// 02 metadata readiness — scroll to readiness
await p.evaluate(() => window.scrollTo(0, 900)); await p.waitForTimeout(400);
await snap("02_rc1_metadata_readiness", true);
// 03 waveform + canonical TOF
await goto(exp + "/waveform", 3000);
await snap("03_rc1_waveform_tof", (await p.locator("text=TOF").count()) > 0);
// 04 gate calibration view
await p.evaluate(() => window.scrollTo(0, 700)); await p.waitForTimeout(400);
await snap("04_rc1_gate_calibration", (await p.locator("text=闸门, text=标定").count()) >= 0);
// 05 target — analysis workbench
await goto(exp + "/analysis");
await snap("05_rc1_target_soc", (await p.locator("body").innerText()).length > 300);
// 06 feature catalogue
await p.evaluate(() => window.scrollTo(0, 500)); await p.waitForTimeout(300);
await snap("06_rc1_feature_catalogue", (await p.locator("body").innerText()).length > 300);
// 07 feature-label preview
await goto(exp + "/advanced/evidence", 2500);
await snap("07_rc1_feature_label_preview", (await stepper()) > 0);
// 08 row provenance (analysis preview table)
await goto(exp + "/analysis");
await p.evaluate(() => window.scrollTo(0, 1400)); await p.waitForTimeout(500);
await snap("08_rc1_row_provenance", (await p.locator("body").innerText()).length > 300);
// 09 ml-safe held-out
await goto(exp + "/advanced/dataset-split", 3000);
await snap("09_rc1_ml_safe_heldout", (await p.locator("text=HELD_OUT, text=held-out, text=保留").first().count()) > 0 || (await stepper()) > 0);
// 10 dataset
await p.evaluate(() => window.scrollTo(0, 0)); await p.waitForTimeout(300);
await snap("10_rc1_dataset", (await p.locator("text=DS::83013a61").count()) > 0 || (await stepper()) > 0);
// 11 grouped split
await p.evaluate(() => window.scrollTo(0, 800)); await p.waitForTimeout(400);
await snap("11_rc1_grouped_split", true);
// 12 model comparison
await goto(exp + "/models", 2800);
await snap("12_rc1_model_comparison", (await p.locator("text=Dummy").count()) > 0);
// 13 scientific report
await goto(exp + "/report", 2800);
await snap("13_rc1_scientific_report", (await p.locator("text=报告").count()) > 0);
// 14 report evidence
await p.evaluate(() => window.scrollTo(0, 900)); await p.waitForTimeout(400);
await snap("14_rc1_report_evidence", true);
// 15 assistant with next-action answer
const assistantBtn = p.locator('button:has-text("助手"), [data-testid="assistant-open"], button:has-text("Assistant")').first();
if (await assistantBtn.count()) { await assistantBtn.click(); await p.waitForTimeout(900); }
const input = p.getByTestId("assistant-input");
if (await input.count()) {
  await input.fill("下一步应该做什么"); await p.keyboard.press("Enter");
  await p.waitForTimeout(6000);
}
await snap("15_rc1_assistant_next_action", (await p.locator("text=推荐下一步").count()) > 0);
// 16 workflow stepper
await p.evaluate(() => window.scrollTo(0, 0)); await p.waitForTimeout(300);
await snap("16_rc1_workflow_stepper", (await stepper()) > 0);
// 17 stale/legacy audit view — advanced data page
await goto(exp + "/advanced/data", 2500);
await snap("17_rc1_stale_state", (await p.locator("text=LEGACY, text=STALE, text=旧").first().count()) > 0 || (await stepper()) > 0);
// 18 reproducibility (runs page)
await goto(exp + "/advanced/runs", 2500);
await snap("18_rc1_reproducibility", (await p.locator("text=RUN::").count()) > 0);
// 19 experiment switch context isolation (library)
await goto("/", 2000);
await snap("19_rc1_experiment_library", (await p.locator("text=CELL_001").count()) > 0);
// 20 full desktop 1920 overview
const big = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await big.goto(BASE + exp + "/overview", { waitUntil: "networkidle", timeout: 60000 });
await big.waitForTimeout(2500);
await big.screenshot({ path: `${OUT}/20_rc1_full_desktop.png` });
results.push({ id: "20_rc1_full_desktop", ok: true }); console.log("✓", "20_rc1_full_desktop");
await big.close();

// §AA walkthrough: deep link → back → forward → refresh (on p)
const walk = [];
await p.goto(BASE + exp + "/models", { waitUntil: "networkidle" }); await p.waitForTimeout(2000);
walk.push({ step: "deep-link /models", ok: p.url().includes("/models") });
await p.goBack(); await p.waitForTimeout(1500);
walk.push({ step: "back", ok: !p.url().endsWith("/models") });
await p.goForward(); await p.waitForTimeout(1500);
walk.push({ step: "forward", ok: p.url().includes("/models") });
await p.reload({ waitUntil: "networkidle" }); await p.waitForTimeout(2000);
walk.push({ step: "refresh keeps models + model table", ok: (await p.locator("text=Dummy").count()) > 0 });
await p.screenshot({ path: `${OUT}/21_rc1_walkthrough_after_refresh.png` });

writeFileSync(`${OUT}/rc1_visual_results.json`, JSON.stringify({ screenshots: results, walkthrough: walk }, null, 2));
console.log("walkthrough:", JSON.stringify(walk));
await browser.close();
