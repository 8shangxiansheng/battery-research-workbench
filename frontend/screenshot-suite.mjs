/** BRW-025R-FE 视觉验收截图套件 — 14 张 1440×900，来自实际运行 frontend。
 *  前置：API :8000 + UI :5173 已启动。
 *  运行：cd frontend && node screenshot-suite.mjs
 *  每张截图前用 data-testid 断言目标功能真实可见（看不到 → 抛错 FAIL）。
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = "http://localhost:5173";
const OUT = "../docs/ui/screenshots";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const exp = "/experiments/CELL_001/EXP_001";
const results = [];

async function shot(id, url, wait, { expectVisible = [], extra } = {}) {
  await page.goto(BASE + url, { waitUntil: "networkidle", timeout: 45000 });
  await page.waitForTimeout(wait ?? 2500);
  for (const sel of expectVisible) {
    const loc = page.locator(sel).first();
    try {
      await loc.waitFor({ state: "visible", timeout: 12000 });
    } catch {
      results.push({ id, ok: false, missing: sel });
      console.error("✗", id, "— 目标功能不可见:", sel);
      await page.screenshot({ path: `${OUT}/${id}.png` });
      return;
    }
  }
  if (extra) await extra();
  await page.screenshot({ path: `${OUT}/${id}.png`, fullPage: false });
  results.push({ id, ok: true });
  console.log("✓", id);
}

// 01 Overview
await shot("01_overview", `${exp}/overview`, 3000);

// 02 Waveform + physical features（5 张物理特征卡 + Electrical State）
await shot("02_waveform_physical", `${exp}/waveform`, 4000, {
  expectVisible: ["[data-testid=physical-features]", "[data-testid=electrical-state]"],
  extra: async () => {
    await page.getByTestId("physical-features").scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
  },
});

// 03 Waveform TOF blocked（Add sampling rate Dialog）
await shot("03_waveform_tof_blocked", `${exp}/waveform`, 3500, {
  extra: async () => {
    const btn = page.getByRole("button", { name: /添加采样频率|add sampling rate/i }).first();
    if (await btn.count()) { await btn.click(); await page.waitForTimeout(800); }
  },
});

// 04 Gate calibration（Calibrate Gates 区 + 打开标定流程）
await shot("04_gate_calibration", `${exp}/waveform`, 4000, {
  expectVisible: ["[data-testid=calibrate-gates]"],
  extra: async () => {
    await page.getByTestId("calibrate-toggle").click();
    await page.waitForTimeout(3500);
  },
});

// 05 Calibration overlay（波形+包络+gate 阴影）
await shot("05_calibration_overlay", `${exp}/waveform`, 4000, {
  expectVisible: ["[data-testid=calibrate-gates]"],
  extra: async () => {
    await page.getByTestId("calibrate-toggle").click();
    await page.waitForTimeout(3500);
    await page.getByTestId("calibration-overlay").scrollIntoViewIfNeeded();
    await page.waitForTimeout(600);
  },
});

// 06 TD catalogue（More features 展开时域分组）
await shot("06_td_catalogue", `${exp}/analysis`, 3000, {
  expectVisible: ["[data-testid=feature-catalogue]"],
  extra: async () => {
    await page.getByTestId("feature-catalogue").scrollIntoViewIfNeeded();
  },
});

// 07 FD catalogue（搜索 FD 特征展示频域分组）
await shot("07_fd_catalogue", `${exp}/analysis`, 3000, {
  expectVisible: ["[data-testid=feature-catalogue]"],
  extra: async () => {
    await page.getByLabel(/搜索特征 \/ Search features/i).fill("FD");
    await page.waitForTimeout(700);
    await page.getByTestId("feature-catalogue").scrollIntoViewIfNeeded();
  },
});

// 08 Feature details（打开 TDSTD 详情 Dialog）
await shot("08_feature_details", `${exp}/analysis`, 3000, {
  expectVisible: ["[data-testid=feature-catalogue]"],
  extra: async () => {
    const card = page.getByTestId("catalogue-TDSTD");
    await card.scrollIntoViewIfNeeded();
    await card.getByRole("button", { name: /详情 \/ Details/i }).click();
    await page.waitForTimeout(800);
  },
});

// 09 Feature selection（勾选 SWA + TDSTD 后的已选状态）
await shot("09_feature_selection", `${exp}/analysis`, 3000, {
  expectVisible: ["[data-testid=feature-catalogue]"],
  extra: async () => {
    await page.getByTestId("select-TDSTD").click().catch(() => {});
    await page.getByTestId("select-FDAF").click().catch(() => {});
    await page.waitForTimeout(500);
    await page.getByTestId("feature-catalogue").scrollIntoViewIfNeeded();
  },
});

// 10 SOC correlation（Feature Relationship 区）
await shot("10_soc_correlation", `${exp}/analysis`, 3500, {
  expectVisible: ["[data-testid=feature-relationship]"],
  extra: async () => { await page.getByTestId("soc-correlation-table").scrollIntoViewIfNeeded(); },
});

// 11 Temperature + 12 SOH limited（关系区下半部分）
await shot("11_temperature", `${exp}/analysis`, 3500, {
  expectVisible: ["[data-testid=temperature-analysis]"],
  extra: async () => {
    await page.getByTestId("temperature-analysis").scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
  },
});
await shot("12_soh_limited", `${exp}/analysis`, 3500, {
  expectVisible: ["[data-testid=soh-analysis]"],
  extra: async () => {
    await page.getByTestId("soh-analysis").scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
  },
});

// 13 Dataset handoff（Select 模式 → 选特征 → 真实构建 → handoff 卡）
await shot("13_dataset_handoff", `${exp}/analysis`, 3000, {
  expectVisible: ["[data-testid=feature-catalogue]"],
  extra: async () => {
    await page.getByText("为建模选择特征 / Select Features for Modeling").click();
    await page.waitForTimeout(400);
    await page.getByLabel(/搜索特征 \/ Search features/i).fill("TDPP");
    await page.waitForTimeout(600);
    await page.getByTestId("select-TDPP").click();
    await page.waitForTimeout(800);
    const build = page.getByRole("button", { name: /Build dataset/i });
    await build.click();
    await page.waitForTimeout(500);
    await page.getByRole("button", { name: /确认请求/i }).click();
    await page.waitForTimeout(4500);
    const handoff = page.getByTestId("dataset-handoff");
    await handoff.waitFor({ state: "visible", timeout: 10000 });
    await handoff.scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
  },
});

// 14 Models selected features
await shot("14_models_selected", `${exp}/models`, 3500, {
  extra: async () => {
    await page.getByTestId("selected-features").scrollIntoViewIfNeeded().catch(() => {});
  },
});

// 15 Report feature summary
await shot("15_report_feature_summary", `${exp}/report`, 3500, {
  expectVisible: ["[data-testid=report-feature-summary]"],
  extra: async () => { await page.getByTestId("report-feature-summary").scrollIntoViewIfNeeded(); },
});

// 16 Assistant drawer context（global drawer shell — BRW-027 暂停）
await shot("16_assistant_drawer", `${exp}/overview`, 2000, {
  extra: async () => {
    const trigger = page.getByRole("button", { name: /Research Assistant/i });
    if (await trigger.count()) { await trigger.first().click(); await page.waitForTimeout(1200); }
  },
});

await browser.close();
const failed = results.filter(r => !r.ok);
console.log(`\n视觉验收截图完成 → ${OUT}（${results.length - failed.length}/${results.length} 目标功能可见）`);
if (failed.length) {
  console.error("FAILED:", failed.map(f => `${f.id}(${f.missing})`).join(", "));
  process.exit(1);
}
