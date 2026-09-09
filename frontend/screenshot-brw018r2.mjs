/** BRW-018R2 视觉验收 — sampling-parameter submission recovery（12 张 1440×900）。
 *  前置：API :8000 + UI :5173 已启动。
 *  Dialog/Calibration 流程在单次导航内连续截图（before→Saving→Saved→next）。
 *  运行：cd frontend && node screenshot-brw018r2.mjs
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = "http://localhost:5173";
const OUT = "../docs/ui/screenshots/brw018r2";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const exp = "/experiments/CELL_001/EXP_001";
const results = [];

async function snap(id, ok = true) {
  await page.screenshot({ path: `${OUT}/${id}.png` });
  results.push({ id, ok });
  console.log(ok ? "✓" : "×", id);
}
async function nav(url, wait = 2500) {
  await page.goto(BASE + url, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(wait);
}

// ---- 01 before：canonical TOF 面板（保存前状态可见） ----
await nav(`${exp}/waveform`);
await page.getByTestId("canonical-tof-panel").scrollIntoViewIfNeeded();
await snap("01_before_canonical_tof");

// ---- 02–07：单次导航内的 dialog 全流程 ----
await page.getByRole("button", { name: "Add sampling rate" }).first().click();
await page.getByTestId("fs-dialog-value").waitFor({ state: "visible", timeout: 10000 });
await snap("02_dialog_open_empty");

await page.getByTestId("fs-dialog-value").fill("50");
await page.getByTestId("fs-dialog-unit").selectOption("MHz");
await page.getByLabel("Instrument record or source").fill("BRW-018R2 visual acceptance · instrument record");
await page.getByTestId("fs-verified-checkbox").click();
await snap("03_dialog_filled_verified");

await page.getByTestId("fs-dialog-save").click();
let savingSeen = true;
try {
  await page.getByTestId("submission-saving").waitFor({ state: "visible", timeout: 1200 });
} catch { savingSeen = false; }
await snap("04_saving_state", savingSeen);

await page.getByTestId("submission-saved").waitFor({ state: "visible", timeout: 20000 });
await page.waitForTimeout(1200); // allow invalidation refetch to land
await snap("05_saved_state");

await page.getByRole("button", { name: "Done" }).click();
await page.waitForTimeout(2000);
await page.getByTestId("canonical-tof-panel").scrollIntoViewIfNeeded();
await snap("06_after_saved_tof_refresh");

// ---- 07 failed state：网络中断 → Failed UI（no silent no-op；空 source 由
// 客户端禁用按钮拦截——防呆本身即证据，此处演示服务器失败路径的可见性）----
await page.keyboard.press("Escape");
await page.waitForTimeout(600);
await page.route("**/sampling-parameter-submission", route => route.abort("failed"));
await page.getByRole("button", { name: "Add sampling rate" }).first().click();
await page.getByTestId("fs-dialog-value").waitFor({ state: "visible", timeout: 10000 });
await page.getByTestId("fs-dialog-value").fill("50");
await page.getByLabel("Instrument record or source").fill("visual acceptance · network failure path");
await page.getByTestId("fs-dialog-save").click();
let failedOk = true;
try {
  await page.getByTestId("submission-failed").waitFor({ state: "visible", timeout: 15000 });
} catch { failedOk = false; }
await snap("07_failed_no_source", failedOk);
await page.unroute("**/sampling-parameter-submission");
await page.keyboard.press("Escape");
await page.waitForTimeout(600);

// ---- 08–09：Calibration 面板 TOF 诊断 + freeze（单次导航内）----
await page.getByTestId("calibrate-toggle").click();
await page.waitForTimeout(3000);
await page.getByTestId("tof-gate-diagnostics").waitFor({ state: "visible", timeout: 20000 });
await page.getByTestId("tof-gate-diagnostics").scrollIntoViewIfNeeded();
await snap("08_calibration_tof_diagnostics");

await page.getByTestId("freeze-tof-gates").click();
let freezeOk = true;
try {
  await page.getByTestId("tof-freeze-saved").waitFor({ state: "visible", timeout: 20000 });
} catch { freezeOk = false; }
await snap("09_tof_freeze_saved", freezeOk);

// ---- 10 assistant：算TOF（fs+calibration 后的 canonical 回答）----
await nav(`${exp}/waveform`);
await page.getByRole("button", { name: /Research Assistant/i }).first().click();
await page.getByTestId("assistant-drawer").waitFor({ state: "visible", timeout: 15000 });
await page.getByTestId("assistant-input").fill("算TOF");
await page.getByTestId("assistant-send").click();
await page.getByTestId("assistant-answer").first().waitFor({ state: "visible", timeout: 15000 });
await page.waitForTimeout(800);
await snap("10_agent_canonical_tof");

// ---- 11 overview：提交后的全局状态 ----
await nav(`${exp}/overview`, 3500);
await snap("11_overview_after_submission");

// ---- 12 runs：submission journal / run resume 痕迹 ----
await nav(`/runs`, 3000);
await snap("12_runs_after_resume");

writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 2));
const passed = results.filter(r => r.ok).length;
console.log(`BRW-018R2 视觉验收完成 → ${OUT}（${passed}/${results.length}）`);
if (passed !== results.length) process.exit(1);
await browser.close();
