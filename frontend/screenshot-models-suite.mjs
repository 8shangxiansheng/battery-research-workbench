/** Models-2 — 8-model suite (SVR/GPR/kNN) surfaced in the SOC 建模 page.
 *  前置：API :8000 + UI :5173 已在运行。只读。
 *  运行：cd frontend && node screenshot-models-suite.mjs
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const OUT = "../docs/ui/screenshots/models-suite";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

await page.goto("http://localhost:5173/experiments/CELL_001/EXP_001/models");
await page.waitForSelector('[data-testid="model-comparison"] tbody tr, table tbody tr', {
  timeout: 40000,
});
await page.waitForTimeout(600);

const rows = await page.locator("table tbody tr").allInnerTexts();
const text = rows.join("\n");
for (const label of ["SVR (RBF)", "GPR", "k-NN (k=10)"]) {
  console.log(text.includes(label) ? `✓ ${label} in table` : `× ${label} MISSING`);
}
const banner = await page.locator("h2").first().innerText();
console.log("banner:", banner);

await page.screenshot({ path: `${OUT}/models-8-suite.png`, fullPage: true });
writeFileSync(`${OUT}/manifest.json`, JSON.stringify({ banner, rows }, null, 2));
await browser.close();
