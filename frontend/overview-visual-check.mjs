import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync } from "node:fs";

const output = "../docs/ui/screenshots/overview-workflow";
mkdirSync(output, { recursive: true });
const browser = await chromium.launch();
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  const writes = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.route("**/api/v1/**", route => {
    if (route.request().method() !== "GET") { writes.push(route.request().url()); return route.abort(); }
    return route.continue();
  });
  await page.goto("http://127.0.0.1:5173/experiments/CELL_001/EXP_001/overview");
  await page.getByTestId("overview-primary").waitFor();
  await page.waitForLoadState("networkidle");
  await page.locator(".js-plotly-plot").nth(1).waitFor();
  console.log((await page.locator("#main-content").innerText()).slice(0, 3500));
  await page.screenshot({ path: `${output}/overview-1440.png` });
  await page.screenshot({ path: `${output}/overview-full.png`, fullPage: true });
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  await page.getByTestId("overview-primary").click();
  await page.getByRole("dialog").waitFor();
  await page.screenshot({ path: `${output}/prerequisites.png` });
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Add sampling rate" }).click();
  await page.getByLabel("Sampling frequency (MHz)").waitFor();
  await page.screenshot({ path: `${output}/sampling-dialog.png` });
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "携带阻断上下文询问助手" }).click();
  await page.getByRole("dialog").getByText("助手未连接").waitFor();
  await page.screenshot({ path: `${output}/assistant-context.png` });
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `${output}/overview-mobile.png`, fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  console.log(JSON.stringify({ errors, blockedWrites: writes, mobileOverflow: overflow, accessibility: axe.violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.map(n => n.target) })) }, null, 2));
  if (errors.length || writes.length || overflow || axe.violations.length) process.exitCode = 1;
} finally { await browser.close(); }
