/** BRW-025R-FE-R1 视觉验收截图套件 — 18 张 1440×900（14_SCREENSHOT_MANIFEST.yaml）。
 *  前置：API :8000 + UI :5173 已启动。
 *  每张截图断言目标功能 data-testid 可见；不可见 → 记 fail 并继续。
 *  运行：cd frontend && node screenshot-suite.mjs
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

async function shot(id, url, { wait = 2500, expectVisible = [], extra } = {}) {
  await page.goto(BASE + url, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(wait);
  let ok = true;
  for (const sel of expectVisible) {
    try {
      await page.locator(sel).first().waitFor({ state: "visible", timeout: 15000 });
    } catch {
      ok = false;
      console.error("✗", id, "— missing:", sel);
      break;
    }
  }
  if (ok && extra) { try { await extra(); } catch (e) { ok = false; console.error("✗", id, String(e).slice(0, 120)); } }
  await page.screenshot({ path: `${OUT}/${id}.png` });
  results.push({ id, ok });
  console.log(ok ? "✓" : "×", id);
}

// ---- workflow setup helpers ----
async function openAnalysis() {
  await page.goto(BASE + exp + "/analysis", { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(2500);
}
async function selectSocTarget() {
  await page.getByTestId("select-target-reference_soc_percent").click();
  await page.waitForTimeout(400);
  await page.getByTestId("to-alignment").click();
  await page.waitForTimeout(1500);
}
async function gotoFeatures() {
  await page.getByTestId("to-features").click();
  await page.waitForTimeout(1200);
}
async function selectDefaultFeatures() {
  for (const f of ["SWA", "BOTTOM_AMP", "TOF_XCORR"]) {
    await page.getByTestId(`quick-${f}`).click().catch(() => {});
    await page.waitForTimeout(250);
  }
}

// 01 Target selection
await shot("01_target_selection", `${exp}/analysis`, {
  expectVisible: ["[data-testid=target-selector]"],
});

// 02 Reference SOC details
await shot("02_target_reference_soc_details", `${exp}/analysis`, {
  expectVisible: ["[data-testid=target-card-reference_soc_percent]"],
  extra: async () => {
    await page.getByTestId("target-card-reference_soc_percent").scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
  },
});

// 03 Alignment summary
await shot("03_alignment_summary", `${exp}/analysis`, {
  extra: async () => {
    await selectSocTarget();
    await page.getByTestId("alignment-summary").waitFor({ state: "visible", timeout: 15000 });
  },
});

// 04 Alignment row provenance
await shot("04_alignment_row_provenance", `${exp}/analysis`, {
  extra: async () => {
    await selectSocTarget();
    await page.getByTestId("alignment-samples").scrollIntoViewIfNeeded();
    await page.locator('[data-testid^="align-row-"]').first().click();
    await page.waitForTimeout(700);
  },
});

// 05 Alignment exclusions
await shot("05_alignment_exclusions", `${exp}/analysis`, {
  extra: async () => {
    await selectSocTarget();
    await page.getByTestId("alignment-exclusions").scrollIntoViewIfNeeded();
    await page.waitForTimeout(600);
  },
});

// 06 Feature–Label table preview
await shot("06_feature_label_table_preview", `${exp}/analysis`, {
  extra: async () => {
    await selectSocTarget();
    await page.getByTestId("to-features").click();
    await page.waitForTimeout(900);
    await selectDefaultFeatures();
    await page.getByTestId("to-relationships").click();
    await page.waitForTimeout(600);
    await page.getByTestId("to-selection").click();
    await page.waitForTimeout(500);
    await page.getByTestId("to-dataset").click();
    await page.waitForTimeout(2500);
    await page.getByTestId("preview-table-btn").click();
    await page.locator('[data-testid^="fl-row-"]').first().waitFor({ state: "visible", timeout: 30000 });
  },
});

// 07 Feature–Label row provenance
await shot("07_feature_label_row_provenance", `${exp}/analysis`, {
  extra: async () => {
    await selectSocTarget();
    await page.getByTestId("to-features").click();
    await page.waitForTimeout(800);
    await selectDefaultFeatures();
    await page.getByTestId("to-relationships").click();
    await page.waitForTimeout(500);
    await page.getByTestId("to-selection").click();
    await page.waitForTimeout(400);
    await page.getByTestId("to-dataset").click();
    await page.waitForTimeout(2200);
    await page.getByTestId("preview-table-btn").click();
    await page.locator('[data-testid^="fl-row-"]').first().waitFor({ state: "visible", timeout: 30000 });
    await page.locator('[data-testid^="fl-row-"]').first().click();
    await page.waitForTimeout(700);
  },
});

// 08 SOC relationship overall
await shot("08_soc_relationship_overall", `${exp}/analysis`, {
  extra: async () => {
    await selectSocTarget();
    await gotoFeatures();
    await selectDefaultFeatures();
    await page.getByTestId("to-relationships").click();
    await page.getByTestId("run-ranking-btn").waitFor({ state: "visible", timeout: 10000 });
    await page.getByTestId("run-ranking-btn").click();
    await page.locator('[data-testid^="rank-"]').first().waitFor({ state: "visible", timeout: 60000 });
    await page.waitForTimeout(400);
  },
});

// 09 SOC charge/discharge columns
await shot("09_soc_charge_discharge", `${exp}/analysis`, {
  extra: async () => {
    await selectSocTarget();
    await gotoFeatures();
    await selectDefaultFeatures();
    await page.getByTestId("to-relationships").click();
    await page.getByTestId("run-ranking-btn").click();
    await page.locator('[data-testid^="rank-"]').first().waitFor({ state: "visible", timeout: 60000 });
    await page.locator('[data-testid^="rank-"]').first().scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
  },
});

// 10 Temperature target state
await shot("10_temperature_target_state", `${exp}/analysis`, {
  expectVisible: ["[data-testid=target-card-temperature_c]"],
  extra: async () => {
    await page.getByTestId("target-card-temperature_c").scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
  },
});

// 11 SOH limited
await shot("11_soh_target_limited", `${exp}/analysis`, {
  expectVisible: ["[data-testid=target-card-soh_capacity_reference_percent]"],
  extra: async () => {
    await page.getByTestId("target-card-soh_capacity_reference_percent").scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
  },
});

// 12 Exploratory ranking
await shot("12_exploratory_feature_ranking", `${exp}/analysis`, {
  extra: async () => {
    await selectSocTarget();
    await gotoFeatures();
    await selectDefaultFeatures();
    await page.getByTestId("to-relationships").click();
    await page.getByTestId("run-ranking-btn").click();
    await page.locator('[data-testid="ranking-mode-badge"]').waitFor({ state: "visible", timeout: 15000 });
    await page.locator('[data-testid^="rank-"]').first().waitFor({ state: "visible", timeout: 60000 });
  },
});

// 13 ML-safe feature selection
await shot("13_ml_safe_feature_selection", `${exp}/analysis`, {
  extra: async () => {
    await selectSocTarget();
    await gotoFeatures();
    await selectDefaultFeatures();
    await page.getByTestId("to-relationships").click();
    await page.waitForTimeout(400);
    await page.getByTestId("to-selection").click();
    await page.getByTestId("mode-mlsafe").click();
    await page.waitForTimeout(1200);
  },
});

// 14 Dataset X/y preview
await shot("14_dataset_x_y_preview", `${exp}/analysis`, {
  extra: async () => {
    await selectSocTarget();
    await gotoFeatures();
    await selectDefaultFeatures();
    await page.getByTestId("to-relationships").click();
    await page.waitForTimeout(400);
    await page.getByTestId("to-selection").click();
    await page.waitForTimeout(400);
    await page.getByTestId("to-dataset").click();
    await page.waitForTimeout(2500);
    await page.getByTestId("build-mlsafe-btn").click();
    await page.getByTestId("dataset-xy-preview").waitFor({ state: "visible", timeout: 10000 });
    await page.waitForTimeout(400);
  },
});

// 15 Dataset eligibility breakdown（预览表格 + 漏斗）
await shot("15_dataset_eligibility_breakdown", `${exp}/analysis`, {
  extra: async () => {
    await selectSocTarget();
    await gotoFeatures();
    await selectDefaultFeatures();
    await page.getByTestId("to-relationships").click();
    await page.waitForTimeout(400);
    await page.getByTestId("to-selection").click();
    await page.waitForTimeout(400);
    await page.getByTestId("to-dataset").click();
    await page.waitForTimeout(2500);
    await page.getByTestId("preview-table-btn").click();
    await page.getByTestId("eligibility-breakdown").waitFor({ state: "visible", timeout: 30000 });
    await page.getByTestId("eligibility-breakdown").scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
  },
});

// 16 Models target/feature summary
await shot("16_models_target_feature_summary", `${exp}/models`, {
  extra: async () => {
    await page.getByTestId("selected-features").scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(400);
  },
});

// 17 Report target/alignment summary
await shot("17_report_target_alignment_summary", `${exp}/report`, {
  extra: async () => {
    await page.getByTestId("report-feature-summary").scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(400);
  },
});

// 18 Analysis full workflow（全 stepper 视图）
await shot("18_analysis_full_workflow", `${exp}/analysis`, {
  expectVisible: ["[data-testid=workflow-stepper]", "[data-testid=target-selector]"],
});

await browser.close();
const failed = results.filter(r => !r.ok);
writeFileSync("/tmp/screenshot-results.json", JSON.stringify(results, null, 2));
console.log(`\nR1 视觉验收截图完成 → ${OUT}（${results.length - failed.length}/${results.length}）`);
if (failed.length) {
  console.error("FAILED:", failed.map(f => f.id).join(", "));
  process.exit(1);
}
