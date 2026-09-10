/** BRW-025R-OV 视觉验收 — Research Overview 首屏（14 张 1440×900 + 1920 宽屏）。
 *  前置：API :8000 + UI :5173 已启动。
 *  只读验收：不提交、不冻结、不改工件。
 *  运行：cd frontend && node screenshot-brw025rov.mjs
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = "http://localhost:5173";
const OUT = "../docs/ui/screenshots/brw025rov";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const results = [];
const exp = "/experiments/CELL_001/EXP_001";

async function newPage(width = 1440) {
  return await browser.newPage({ viewport: { width, height: 900 } });
}

async function snap(p, id, ok = true) {
  await p.screenshot({ path: `${OUT}/${id}.png` });
  results.push({ id, ok });
  console.log(ok ? "✓" : "×", id);
}

// ================= 1440 桌面主流程 =================
const p = await newPage(1440);

// 01 首屏整体（banner + metadata strip + snapshots）
await p.goto(BASE + exp + "/overview", { waitUntil: "networkidle", timeout: 60000 });
await p.waitForTimeout(2500);
await snap(p, "01_overview_first_screen",
  await p.getByTestId("research-status-banner").count() > 0);

// 02 Metadata Strip 特写（滚到顶部）
await p.evaluate(() => window.scrollTo(0, 0));
await p.waitForTimeout(300);
await snap(p, "02_metadata_strip",
  await p.getByTestId("metadata-strip").count() > 0);

// 03 banner 特写（科研状态 + 携带上下文询问助手）
await snap(p, "03_research_status_banner",
  (await p.getByTestId("research-status-banner").innerText()).includes("受限") ||
  (await p.getByTestId("research-status-banner").innerText()).includes("阻断"));

// 04 Electrical Snapshot 特写
await p.getByTestId("electrical-snapshot").scrollIntoViewIfNeeded();
await p.waitForTimeout(400);
await snap(p, "04_electrical_snapshot",
  (await p.getByTestId("electrical-snapshot").innerText()).includes("Apparent CE"));

// 05 TOF Snapshot 特写（canonical method + 双 gate + coverage 区分）
await snap(p, "05_tof_snapshot",
  (await p.getByTestId("tof-snapshot").innerText()).includes("SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1"));

// 06 coverage 区分特写（waveform ≠ eligible）
const covText = await p.getByTestId("tof-coverage").innerText();
await snap(p, "06_coverage_distinction", covText.includes("≠"));

// 07 Readiness Matrix + Quick Actions + limitations
await p.getByTestId("readiness-matrix").scrollIntoViewIfNeeded();
await p.waitForTimeout(400);
await snap(p, "07_readiness_matrix_actions",
  (await p.getByTestId("readiness-matrix").count()) > 0 &&
  (await p.getByTestId("quick-actions").count()) > 0);

// 08 limitations 首屏可见特写
await snap(p, "08_limitations_first_screen",
  (await p.getByTestId("limitations-first-screen").innerText()).includes("provisional") ||
  (await p.getByTestId("limitations-first-screen").innerText()).includes("provisional".toUpperCase()));

// 09 Scientific Snapshot 特写
await p.getByTestId("scientific-snapshot").scrollIntoViewIfNeeded();
await p.waitForTimeout(400);
await snap(p, "09_scientific_snapshot",
  (await p.getByTestId("leading-candidate").innerText()).length > 0);

// 10 Model Baseline Comparison（5 策略 + stale refresh required）
await p.getByTestId("model-baseline-comparison").scrollIntoViewIfNeeded();
await p.waitForTimeout(400);
await snap(p, "10_model_baseline_comparison",
  (await p.getByTestId("model-refresh-required").count()) > 0 &&
  (await p.getByTestId("model-comparison-table").innerText()).includes("DUMMY_MEAN"));

// 11 Quick Actions ≤3 特写
const quickActions = await p.getByTestId(/^quick-action-/).count();
await p.getByTestId("quick-actions").scrollIntoViewIfNeeded();
await snap(p, "11_quick_actions_max3", quickActions >= 1 && quickActions <= 3);

// 12 Assistant 注入上下文（打开抽屉 + 发送后可见科研上下文回显）
await p.evaluate(() => window.scrollTo(0, 0));
await p.getByTestId("ask-assistant-with-context").click();
await p.getByTestId("assistant-drawer").waitFor({ state: "visible", timeout: 15000 });
await p.getByTestId("assistant-input").fill("当前实验的科研状态如何？");
await p.getByTestId("assistant-send").click();
await p.getByTestId("assistant-answer").first().waitFor({ state: "visible", timeout: 20000 });
await p.waitForTimeout(800);
await snap(p, "12_assistant_injected_context", true);
await p.keyboard.press("Escape");
await p.waitForTimeout(500);

// 13 inline fs 配置区（已验证态 → 显示已配置；未验证 → 显示表单）
await p.getByTestId("fs-inline-config").scrollIntoViewIfNeeded();
await p.waitForTimeout(300);
await snap(p, "13_fs_inline_config",
  (await p.getByTestId("fs-inline-config").innerText()).length > 0);

await p.close();

// ================= 1920 宽屏利用 =================
const w = await newPage(1920);
await w.goto(BASE + exp + "/overview", { waitUntil: "networkidle", timeout: 60000 });
await w.waitForTimeout(2500);
await snap(w, "14_widescreen_1920",
  (await w.getByTestId("metadata-strip").count()) > 0);
await w.close();

writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 2));
const passed = results.filter(r => r.ok).length;
console.log(`BRW-025R-OV 视觉验收完成 → ${OUT}（${passed}/${results.length}）`);
if (passed !== results.length) process.exit(1);
await browser.close();
