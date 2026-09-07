/** BRW-025R 视觉验收截图套件（§36）— 1440×900，来自实际运行 frontend。
 *  前置：API :8000 + UI :5173 已启动。
 *  运行：cd frontend && node screenshot-suite.mjs
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = "http://localhost:5173";
const OUT = "../docs/ui/screenshots";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const exp = "/experiments/CELL_001/EXP_001";

async function shot(id, url, wait = 2500, extra) {
  await page.goto(BASE + url, { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForTimeout(wait);
  if (extra) await extra();
  await page.screenshot({ path: `${OUT}/${id}.png`, fullPage: false });
  console.log("✓", id);
}

// 01 Overview
await shot("01_overview", `${exp}/overview`, 3000);

// 02 Waveform
await shot("02_waveform", `${exp}/waveform`, 3500);

// 03 Waveform TOF blocked — 打开 Add sampling rate Dialog 展示 blocked UX
await shot("03_waveform_tof_blocked", `${exp}/waveform`, 3500, async () => {
  const btn = page.getByRole("button", { name: /add sampling rate/i }).first();
  if (await btn.count()) {
    await btn.click();
    await page.waitForTimeout(800);
  }
});

// 04 Analysis core
await shot("04_analysis_core", `${exp}/analysis`, 2500);

// 05 Analysis expanded（展开 More features）
await shot("05_analysis_expanded", `${exp}/analysis`, 2000, async () => {
  const more = page.locator('[data-testid="more-features"] summary');
  if (await more.count()) await more.click();
  await page.waitForTimeout(800);
});

// 06 Models
await shot("06_models", `${exp}/models`, 3000);

// 07 Report
await shot("07_report", `${exp}/report`, 2500);

// 08 Advanced parameters
await shot("08_advanced_parameters", `${exp}/advanced/parameters`, 2500);

// 09 Assistant Drawer（打开 Sheet）
await shot("09_assistant_drawer", `${exp}/overview`, 2000, async () => {
  const trigger = page.getByRole("button", { name: /Research Assistant/i });
  if (await trigger.count()) {
    await trigger.first().click();
    await page.waitForTimeout(1200);
  }
});

// 10 Empty state（Advanced → Artifacts 无产物时的友好空态）
await shot("10_empty_state", `${exp}/advanced/artifacts`, 2000);

await browser.close();
console.log("视觉验收截图完成 →", OUT);
