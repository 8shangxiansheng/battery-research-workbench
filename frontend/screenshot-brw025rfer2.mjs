/** BRW-025R-FE-R2 视觉验收 — Feature–Label Preview / X-y / ML-safe Review（16 张 1440×900）。
 *  前置：API :8000 + UI :5173 已启动。只读验收（不点最终 Build）。
 *  运行：cd frontend && node screenshot-brw025rfer2.mjs
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = "http://localhost:5173";
const OUT = "../docs/ui/screenshots/brw025rfer2";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const results = [];
const exp = "/experiments/CELL_001/EXP_001";

async function snap(p, id, ok = true) {
  await p.screenshot({ path: `${OUT}/${id}.png` });
  results.push({ id, ok });
  console.log(ok ? "✓" : "×", id);
}

// ============ Exploratory 预览主链路（单页会话内连续截图） ============
const p = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await p.goto(BASE + exp + "/analysis", { waitUntil: "networkidle", timeout: 60000 });
await p.waitForTimeout(2000);

// 选目标（SOC）→ 走到 dataset 步骤
const socCard = p.locator("[data-testid=target-reference_soc_percent]");
if (await socCard.count()) { await socCard.click(); await p.waitForTimeout(800); }

// 直接通过 stepper 进 dataset 步骤（避免长链路）
await p.getByRole("button", { name: /数据集 \/ Dataset/ }).first().click().catch(() => {});
await p.waitForTimeout(600);

// 勾选 SWA（dataset 步骤内的 preview 需要 features；若 stepper 页面无 chips 则回 features 步）
let chip = p.locator("[data-testid=quick-SWA]");
if (!(await chip.count())) {
  await p.getByRole("button", { name: /特征 \/ Features/ }).first().click();
  await p.waitForTimeout(500);
  chip = p.locator("[data-testid=quick-SWA]");
}
if (await chip.count()) await chip.click();
await p.waitForTimeout(300);
// 回 dataset 步骤
await p.getByRole("button", { name: /数据集 \/ Dataset/ }).first().click();
await p.waitForTimeout(800);

// 01 预览前（按钮态）
await p.getByTestId("feature-label-table").scrollIntoViewIfNeeded();
await snap(p, "01_preview_before");

// 02 触发预览
await p.getByTestId("preview-table-btn").click();
await p.getByTestId("feature-label-summary").waitFor({ state: "visible", timeout: 20000 });
await p.waitForTimeout(500);
await snap(p, "02_preview_summary_cards",
  (await p.getByTestId("summary-state").innerText()).includes("PREVIEW_DRAFT"));
await p.getByTestId("col-header-SWA").waitFor({ state: "visible", timeout: 10000 });

// 03 X/y/rows/grain/spec hash 卡片特写
await snap(p, "03_summary_x_y_rows_grain",
  (await p.getByTestId("summary-grain").innerText()).includes("eligible MeasurementEvent"));

// 04 eligibility funnel + breakdown
await p.getByTestId("eligibility-breakdown").scrollIntoViewIfNeeded();
await snap(p, "04_eligibility_funnel_breakdown",
  (await p.getByTestId("funnel-eligible").innerText()) === "3,995");

// 05 表格中英列头 + units
await p.getByTestId("col-header-SWA").scrollIntoViewIfNeeded();
await snap(p, "05_table_bilingual_units",
  (await p.getByTestId("col-header-SWA").innerText()).includes("表面波幅值"));

// 06 列详情 drawer（SWA）
await p.getByTestId("col-header-SWA").click();
await p.getByTestId("feature-column-details").waitFor({ state: "visible", timeout: 10000 });
await snap(p, "06_column_details_swa",
  (await p.getByTestId("feature-column-details").innerText()).includes("DEFINED_AND_VALIDATED"));
await p.keyboard.press("Escape");
await p.waitForTimeout(500);

// 07 TOF_XCORR 列详情（canonical method + fs + GC record）
// 需要勾 TOF_XCORR 后重跑预览；回 features 步勾选
await p.getByRole("button", { name: /特征 \/ Features/ }).first().click();
await p.waitForTimeout(500);
const tofChip = p.locator("[data-testid=quick-TOF_XCORR]");
if (await tofChip.count()) await tofChip.click();
await p.getByRole("button", { name: /数据集 \/ Dataset/ }).first().click();
await p.waitForTimeout(500);
await p.getByTestId("preview-table-btn").click();
await p.getByTestId("col-header-TOF_XCORR").waitFor({ state: "visible", timeout: 20000 });
await p.waitForTimeout(600);
await p.getByTestId("col-header-TOF_XCORR").click();
await p.getByTestId("feature-column-details").waitFor({ state: "visible", timeout: 15000 });
await snap(p, "07_column_details_tof_provenance",
  (await p.getByTestId("feature-column-details").innerText()).includes("SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1"));
await p.keyboard.press("Escape");
await p.waitForTimeout(500);

// 08 分页（第二页）
await p.getByTestId("fl-pagination").scrollIntoViewIfNeeded();
const nextDisabled = await p.getByText("下一页").isDisabled().catch(() => true);
if (!nextDisabled) {
  await p.getByText("下一页").click();
  await p.waitForTimeout(400);
}
await snap(p, "08_pagination_page2", !nextDisabled);

// 09 状态过滤
await p.getByTestId("fl-state-filter").selectOption("charge");
await p.waitForTimeout(400);
await snap(p, "09_filter_state_charge", true);

// 10 搜索
await p.getByTestId("fl-search").fill("::10");
await p.waitForTimeout(400);
await snap(p, "10_search_event_id", true);

// 11 行 provenance drawer（先清过滤）
await p.getByTestId("fl-search").fill("");
await p.waitForTimeout(400);
await p.locator('[data-testid^=fl-row-]').first().click();
await p.getByTestId("feature-label-row-provenance").waitFor({ state: "visible", timeout: 10000 });
await snap(p, "11_row_provenance_drawer",
  (await p.getByTestId("feature-label-row-provenance").innerText()).includes("Electrical locator"));
await p.keyboard.press("Escape");
await p.waitForTimeout(500);

// 12 ambiguous rows
await p.getByTestId("toggle-ambiguous").scrollIntoViewIfNeeded();
await p.getByTestId("toggle-ambiguous").click();
await p.getByTestId("ambiguous-rows-table").waitFor({ state: "visible", timeout: 10000 });
await snap(p, "12_ambiguous_rows_inspect",
  (await p.getByTestId("ambiguous-rows-table").innerText()).includes("未选择"));

// ============ ML-safe split 感知（新会话） ============
await p.goto(BASE + exp + "/analysis", { waitUntil: "networkidle", timeout: 60000 });
await p.waitForTimeout(2000);
const soc2 = p.locator("[data-testid=target-reference_soc_percent]");
if (await soc2.count()) { await soc2.click(); await p.waitForTimeout(600); }
// features 步：勾 amplitude_a_u（chips，匹配已物化 ML-safe 分析）
await p.getByRole("button", { name: /特征 \/ Features/ }).first().click();
await p.waitForTimeout(500);
const amp = p.locator("[data-testid=quick-amplitude_a_u]");
console.log("  [mlsafe] amp chip:", await amp.count());
if (await amp.count()) await amp.click();
// ML-safe 模式
await p.getByRole("button", { name: /筛选 \/ Selection/ }).first().click();
await p.waitForTimeout(500);
const mlsafe = p.locator("[data-testid=mode-mlsafe]");
console.log("  [mlsafe] mode radio:", await mlsafe.count());
if (await mlsafe.count()) await mlsafe.click();
await p.waitForTimeout(400);
console.log("  [mlsafe] analysis found:", await p.getByTestId("ml-safe-analysis-found").count());
await p.waitForTimeout(600);
// 回 dataset 步（带 split 上下文）
await p.getByRole("button", { name: /数据集 \/ Dataset/ }).first().click();
await p.waitForTimeout(600);
console.log("  [mlsafe] preview btn:", await p.getByTestId("preview-table-btn").count());
await p.getByTestId("preview-table-btn").click();
await p.waitForTimeout(2500);

// 13 HELD_OUT 后端封锁摘要
const redaction = await p.getByTestId("redaction-summary").count();
await p.getByTestId("feature-label-table").scrollIntoViewIfNeeded();
await snap(p, "13_mlsafe_redaction_summary", redaction > 0);

// 14 HELD_OUT 行已封锁（badge + EyeOff cell）
const heldBadge = await p.locator("text=HELD_OUT").first().count();
await snap(p, "14_held_out_redacted_rows", heldBadge > 0 || redaction > 0);

// 15 stale TOF banner（amplitude_a_u spec 匹配已物化 DS → legacy TOF → refresh required）
await p.getByTestId("stale-tof-banner").scrollIntoViewIfNeeded().catch(() => {});
await snap(p, "15_stale_tof_banner",
  (await p.getByTestId("stale-tof-banner").count()) > 0);

// 16 Build 确认对话框（不点最终构建——只看确认块）
await p.getByTestId("build-mlsafe-btn").scrollIntoViewIfNeeded().catch(() => {});
const buildBtn = p.getByTestId("build-mlsafe-btn");
if (await buildBtn.count()) {
  await buildBtn.click();
  await p.getByTestId("build-confirm-spec").waitFor({ state: "visible", timeout: 10000 }).catch(() => {});
  await snap(p, "16_build_confirm_spec",
    (await p.getByTestId("build-confirm-spec").count()) > 0);
} else {
  await snap(p, "16_build_confirm_spec", false);
}

writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 2));
const passed = results.filter(r => r.ok).length;
console.log(`BRW-025R-FE-R2 视觉验收完成 → ${OUT}（${passed}/${results.length}）`);
if (passed !== results.length) process.exit(1);
await browser.close();
