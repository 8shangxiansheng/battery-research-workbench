/** BRW-027R 视觉验收截图套件 — 12 张 1440×900（15_VISUAL_ACCEPTANCE_MANIFEST.yaml）。
 *  前置：API :8000 + UI :5173 已启动。
 *  每张截图断言目标功能 data-testid 可见；不可见 → FAIL。
 *  运行：cd frontend && node screenshot-assistant.mjs
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
  if (ok && extra) { try { await extra(); } catch (e) { ok = false; console.error("✗", id, String(e).slice(0, 140)); } }
  await page.screenshot({ path: `${OUT}/${id}.png` });
  results.push({ id, ok });
  console.log(ok ? "✓" : "×", id);
}

async function openDrawer() {
  await page.getByRole("button", { name: /Research Assistant/i }).first().click();
  await page.getByTestId("assistant-drawer").waitFor({ state: "visible", timeout: 15000 });
  await page.waitForTimeout(1200);
}
async function ask(msg) {
  await page.getByTestId("assistant-input").fill(msg);
  await page.getByTestId("assistant-send").click();
  await page.waitForTimeout(3000);
}

// 01 SOC goal
await shot("01_assistant_soc_goal", `${exp}/analysis`, {
  extra: async () => { await openDrawer(); await ask("帮我研究SOC"); },
});

// 02 alignment check
await shot("02_assistant_alignment_check", `${exp}/analysis`, {
  extra: async () => { await openDrawer(); await ask("同步对齐怎么样？"); },
});

// 03 feature relationship
await shot("03_assistant_feature_relationship", `${exp}/analysis`, {
  extra: async () => { await openDrawer(); await ask("哪些特征和SOC关系明显？"); },
});

// 04 candidate features
await shot("04_assistant_candidate_features", `${exp}/analysis`, {
  extra: async () => { await openDrawer(); await ask("有哪些特征可以选？"); },
});

// 05 ML-safe confirmation wording
await shot("05_assistant_ml_safe_confirmation", `${exp}/analysis`, {
  extra: async () => { await openDrawer(); await ask("用这些特征构建ML-safe数据集"); },
});

// 06 waiting for sampling rate（新实验场景 + TOF blocked 语义）
await shot("06_assistant_waiting_for_sampling_rate", `${exp}/waveform`, {
  extra: async () => {
    await openDrawer();
    await ask("算TOF微秒");
    await page.waitForTimeout(600);
  },
});

// 07 SOH blocked
await shot("07_assistant_soh_blocked", `${exp}/analysis`, {
  extra: async () => {
    await openDrawer();
    await ask("训练SOH模型");
    await page.locator("[data-testid=assistant-block]").first().waitFor({ state: "visible", timeout: 10000 });
  },
});

// 08 model interpretation
await shot("08_assistant_model_interpretation", `${exp}/analysis`, {
  extra: async () => { await openDrawer(); await ask("这个模型效果怎么样？"); },
});

// 09 evidence view
await shot("09_assistant_evidence_view", `${exp}/analysis`, {
  extra: async () => { await openDrawer(); await ask("这个结论有什么证据？"); },
});

// 10 report generation
await shot("10_assistant_report_generation", `${exp}/report`, {
  extra: async () => { await openDrawer(); await ask("生成这次SOC研究报告"); },
});

// 11 waveform context
await shot("11_assistant_waveform_context", `${exp}/waveform`, {
  expectVisible: ["[data-testid=physical-features]"],
  extra: async () => {
    await openDrawer();
    await ask("同步对齐怎么样？");
  },
});

// 12 target switch
await shot("12_assistant_target_switch", `${exp}/analysis`, {
  extra: async () => {
    await openDrawer();
    await ask("帮我研究SOC");
    await page.waitForTimeout(1200);
    await ask("换成温度看看");
  },
});

await browser.close();
const failed = results.filter(r => !r.ok);
writeFileSync("/tmp/assistant-screenshot-results.json", JSON.stringify(results, null, 2));
console.log(`\nBRW-027R 视觉验收截图完成 → ${OUT}（${results.length - failed.length}/${results.length}）`);
if (failed.length) {
  console.error("FAILED:", failed.map(f => f.id).join(", "));
  process.exit(1);
}
