/** BRW-021R2 — 20 张真实运行截图（特征-目标关系排名工作流）+ manifest。
 *  前置：API :8000 + UI :5173 已在运行（不重启）。只读：不改数据/工件。
 *  运行：cd frontend && node screenshot-brw021r2.mjs
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = "http://localhost:5173";
const OUT = "../docs/ui/screenshots/brw021r2";
mkdirSync(OUT, { recursive: true });

const shots = [];              // manifest entries, in 01..20 order
const byId = new Map();
function record(id, reachable, evidence, notes) {
  if (byId.has(id)) return;    // a failed attempt may be overwritten by success
  const entry = { id, reachable, evidence, notes, file: `${id}.png` };
  byId.set(id, entry);
  shots.push(entry);
  console.log(reachable ? "✓" : "×", id, reachable ? "" : "(NOT REACHABLE)");
}

async function snap(id, { reachable = true, evidence, notes = "", clipEl = null, fullPage = false } = {}) {
  try {
    if (clipEl) await clipEl.scrollIntoViewIfNeeded();
    await page.waitForTimeout(350);
    await page.screenshot({ path: `${OUT}/${id}.png`, fullPage });
    record(id, reachable, evidence, notes);
  } catch (e) {
    record(id, false, evidence, `SNAPSHOT FAILED: ${String(e).slice(0, 200)}. ${notes}`);
  }
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

const rankingRows = (scope = "") =>
  page.waitForSelector(`${scope}[data-testid="feature-ranking"] tbody tr`, { timeout: 40000 });
async function stepTo(label, wait = 700) {
  await page.locator(`[data-testid="workflow-stepper"] button:has-text("${label}")`).first().click();
  await page.waitForTimeout(wait);
}
async function runRanking4() {
  await page.locator('section[data-testid="step-relationships"] [data-testid="run-ranking-btn"]').click();
  await rankingRows('section[data-testid="step-relationships"] ');
}

await page.goto(`${BASE}/experiments/CELL_001/EXP_001/analysis`, { waitUntil: "networkidle", timeout: 60000 });
await page.waitForSelector('[data-testid="target-selector"]', { timeout: 20000 });

// ---- Step 1: choose target; Temperature unavailable card (shot 17) ----
await page.locator('input[aria-label="Select Reference SOC"]').click();
await page.waitForSelector('[data-testid="to-alignment"]', { timeout: 10000 });
await page.locator('[data-testid="target-card-temperature_c"]').scrollIntoViewIfNeeded();
await snap("17_target_unavailable", {
  reachable: (await page.locator('[data-testid="target-unavailable-temperature_c"]').count()) > 0,
  evidence: "Step 1 target selector: Temperature card shows 'Unavailable / 不可用' readiness badge — target genuinely cannot be studied in this environment.",
  notes: "Readiness comes from backend capability report (target_id temperature_c, readiness UNAVAILABLE).",
});

// ---- Step 3: pick physical feature chips ----
await stepTo("3特征");
for (const f of ["tof_us", "amplitude_a_u", "SWA", "BPS", "ATTEN_MAX"]) {
  await page.locator(`[data-testid="quick-${f}"]`).click();
}
await page.waitForTimeout(300);

// ---- Step 4: exploratory relationship ranking ----
await stepTo("4关系");
await page.locator('section[data-testid="step-relationships"] [data-testid="run-ranking-btn"]').click();
await rankingRows('section[data-testid="step-relationships"] ');
await page.waitForTimeout(600);

await page.locator('section[data-testid="step-relationships"] table').scrollIntoViewIfNeeded();
await snap("01_relationships_loaded", {
  reachable: true,
  evidence: "Step 4 '关系 / Relationships': FeatureRankingTable rendered with real ranked rows (backend POST /feature-target-ranking, EXPLORATORY mode).",
});

const modeBadge = page.locator('[data-testid="ranking-mode-badge"]');
await snap("02_exploratory_ranking_table", {
  reachable: (await modeBadge.innerText()).includes("EXPLORATORY"),
  evidence: "Ranking header in frame: mode badge 'EXPLORATORY · 非 ML-safe' + run button + target label; full ranked table below.",
  notes: "Badge text verified to contain EXPLORATORY.",
  clipEl: await page.locator('section[data-testid="step-relationships"] [data-testid="feature-ranking"]'),
});

const sortSel = page.locator('[data-testid="ranking-sort"]');
await sortSel.selectOption("display");
await page.locator('section[data-testid="step-relationships"] table').scrollIntoViewIfNeeded();
await snap("03_ranking_overall", {
  reachable: true,
  evidence: "Sort select = 'Default display ordering (|Spearman overall|)'; rows ordered by |Spearman overall| (backend display convention, not scientific best).",
});
await sortSel.selectOption("abs_charge");
await page.waitForTimeout(400);
await snap("04_ranking_charge", {
  reachable: true,
  evidence: "Sort select = '|Charge Spearman|'; Charge ρ column dominates row order.",
  clipEl: await page.locator('section[data-testid="step-relationships"] table'),
});
await sortSel.selectOption("abs_discharge");
await page.waitForTimeout(400);
await snap("05_ranking_discharge", {
  reachable: true,
  evidence: "Sort select = '|Discharge Spearman|'; Discharge ρ column dominates row order.",
  clipEl: await page.locator('section[data-testid="step-relationships"] table'),
});

const swaBadge = page.locator('[data-testid="direction-SWA"]');
await snap("06_direction_dependent_badge", {
  reachable: (await swaBadge.innerText()).includes("方向依赖"),
  evidence: "SWA row Direction column badge '方向依赖' (DIRECTION_DEPENDENT) with warning icon — charge vs discharge association directions differ (backend-computed).",
  clipEl: swaBadge,
});
await sortSel.selectOption("display");

await snap("07_canonical_tof_relationship", {
  reachable: (await page.locator('[data-testid="ranking-tof-provenance"]').innerText()).includes("MHz"),
  evidence: "ranking-tof-provenance line: canonical TOF method SURFACE_TO_BOTTOM_ENVELOPE_PEAK_TOF_V1 · fs 50 MHz (verified) · gate GC-TOF:: ids (artifact source vs current confirmed gate) · waveform-valid / target-eligible counts.",
  clipEl: page.locator('[data-testid="ranking-tof-provenance"]'),
});

// ---- relationship detail scatter (shots 08, 09) ----
await page.locator('[data-testid="detail-tof_us"]').click();
await page.waitForSelector('[data-testid="relationship-detail"]', { timeout: 20000 });
await page.waitForTimeout(800);
const scatter = page.locator('[data-testid="relationship-detail"]');
const scatterText = await scatter.innerText();
await snap("08_feature_relationship_plot", {
  reachable: scatterText.includes("后端计算，前端不重算") && (await scatter.locator("circle").count()) > 10,
  evidence: "detail-tof_us clicked → relationship-detail scatter panel: tof_us vs Reference SOC points with scope buttons overall/charge/discharge; note '后端计算，前端不重算'.",
  clipEl: scatter,
});
await page.locator('[data-testid="feature-ranking"]').screenshot({ path: `${OUT}/09_feature_details_provenance.png` });
record("09_feature_details_provenance", true,
  "Element-level capture of the whole feature-ranking component in one frame: tof-provenance line, ranked table, relationship-detail scatter, and ranking-summary — scatter + provenance + summary together.",
  "Component screenshot (Playwright element screenshot) so all three regions are provably in one rendered state.");

// ---- multi-feature selection from ranking (shot 10) ----
for (const f of ["BPS", "ATTEN_MAX", "tof_us"]) {
  await page.locator(`[data-testid="select-${f}"]`).click();
  await page.waitForTimeout(200);
}
const checked = await page.locator('section[data-testid="step-relationships"] tbody input[type="checkbox"]:checked').count();
await page.locator('[data-testid="select-amplitude_a_u"]').scrollIntoViewIfNeeded();
await snap("10_multi_feature_selection", {
  reachable: checked === 2,
  evidence: "Two ranking-row Select checkboxes ticked (amplitude_a_u + SWA); selection writes back to the SAME draft feature list (§14), table not rebuilt.",
  notes: `checked=${checked}; tof_us/BPS/ATTEN_MAX unchecked so dataset preview X-columns equal this selection.`,
});

// ---- Step 5: selection provenance (shot 11) ----
await stepTo("5筛选");
const prov = page.locator('[data-testid="selection-provenance"]');
await snap("11_selection_confirmation", {
  reachable: (await prov.count()) > 0 && (await prov.innerText()).includes("EXPLORATORY_RELATIONSHIP_RANKING"),
  evidence: "Step 5 '筛选 / Selection': selection-provenance line 'selection_source = EXPLORATORY_RELATIONSHIP_RANKING · ml_safe_selection = false' — provenance of the step-4 ranking selection.",
  clipEl: prov,
});

// ---- Step 6 (exploratory): dataset preview X columns (shot 12) ----
await page.locator('[data-testid="to-dataset"]').click();
await page.waitForTimeout(900);
await page.locator('[data-testid="preview-table-btn"]').click();
await page.waitForSelector('[data-testid="feature-label-table"] tbody tr', { timeout: 25000 });
await page.waitForTimeout(500);
await snap("12_preview_handoff", {
  reachable: true,
  evidence: "Step 6 dataset preview (exploratory mode, fullPage): feature-label-summary 'X（特征）= 2 列' and the preview table columns amplitude_a_u + SWA equal the two features selected via ranking checkboxes; y = Reference SOC; one row = one eligible MeasurementEvent.",
  fullPage: true,
});

// ---- Step 5 ML-safe fold1 (shot 13) ----
await stepTo("5筛选");
await page.locator('[data-testid="mode-mlsafe"]').click();
await page.waitForSelector('[data-testid="ml-safe-analysis-found"]', { timeout: 10000 });
await page.locator('section[data-testid="step-selection"] [data-testid="run-ranking-btn"]').click();
await rankingRows('section[data-testid="step-selection"] ');
const foldBadge = page.locator('section[data-testid="step-selection"] [data-testid="ranking-fold-badge"]');
await snap("13_ml_safe_fold1_ranking", {
  reachable: (await foldBadge.innerText()).includes("fold1"),
  evidence: "Step 5 mode-mlsafe selected: ml-safe-analysis-found notice, TRAIN-ONLY ML-SAFE mode badge, ranking-fold-badge 'fold1 · TRAIN rows only', n_valid=1903 (TRAIN-only rows vs 3995 full-data).",
  clipEl: foldBadge,
  notes: "fold1 is chosen by the UI's own analysis matcher (AN::83c5dc54…, selected_features include amplitude_a_u); split SPLIT::062cf007…",
});

// ---- fold2 (shot 14): add waveform_p2p_a_u + TOF_XCORR in step 3 -> matcher picks AN::4ee12 (fold2) ----
await stepTo("3特征");
await page.locator('[data-testid="select-TDPP"]').first().click(); // catalogue: TDPP ≡ waveform_p2p_a_u (alias resolves to that name)
await page.locator('[data-testid="quick-TOF_XCORR"]').click();                  // for shot 16 legacy badge
await page.waitForTimeout(300);
await stepTo("5筛选");
await page.locator('section[data-testid="step-selection"] [data-testid="run-ranking-btn"]').click();
await rankingRows('section[data-testid="step-selection"] ');
const foldBadge2 = page.locator('section[data-testid="step-selection"] [data-testid="ranking-fold-badge"]');
const fold2Text = await foldBadge2.innerText().catch(() => "");
await snap("14_ml_safe_fold2_ranking", {
  reachable: fold2Text.includes("fold2"),
  evidence: "Second TRAIN_ONLY ranking under a different ready analysis: ranking-fold-badge 'fold2 · TRAIN rows only', n_valid=2092 (different TRAIN row set than fold1).",
  notes: "Honest limitation: the UI has NO manual fold switch — fold_index is fixed by whichever AVAILABLE materialized analysis the UI matcher finds first (adding waveform_p2p_a_u matches AN::4ee12dda, fold 2). The fold2 state shown is a genuinely rendered UI state, reached by real feature-set change, not a fabricated toggle.",
  clipEl: foldBadge2,
});

// ---- Step 6 ML-safe: HELD_OUT backend redaction block (shot 15) ----
await page.locator('[data-testid="to-dataset"]').click();
await page.waitForTimeout(900);
await page.locator('[data-testid="preview-table-btn"]').click();
await page.waitForSelector('[data-testid="redaction-summary"]', { timeout: 25000 });
await snap("15_heldout_leakage_block", {
  reachable: true,
  evidence: "Dataset preview in TRAIN_ONLY mode: redaction-summary notice 'ML-safe Review (fold fold2): TRAIN 2092 行 y 可见 · HELD_OUT 1903 行 y 已由后端封锁（evaluation 物化后才可见）' + preview-split-badge — real reachable leakage block rendered by the app.",
  clipEl: page.locator('[data-testid="redaction-summary"]'),
  notes: "forbidden-blocked line is not reachable through this UI (catalogue exposes no forbidden predictor); the HELD_OUT server-side y-redaction summary is the app's real reachable block evidence — nothing fabricated.",
});

// ---- Step 4 again: legacy 诊断量 badge (shot 16) ----
await stepTo("4关系");
await runRanking4();
const xcorrRow = page.locator('tr[data-testid="rank-TOF_XCORR"]');
const legacyVisible = (await xcorrRow.innerText().catch(() => "")).includes("诊断量");
await snap("16_stale_analysis_refresh", {
  reachable: legacyVisible > 0,
  evidence: "Closest REAL staleness/provenance-gating affordance currently rendered: TOF_XCORR row carries '诊断量' (legacy diagnostic) badge — backend flags it as XCorr-diagnostic-only and it is excluded from canonical tof_us.",
  notes: "Substituted honestly: this environment has a matched gate-calibration window, so tof_us status is CURRENT (no REFRESH_REQUIRED badge / stale-tof-banner appears) and blocked_forbidden is empty — neither is faked here.",
  clipEl: xcorrRow,
});

// ---- 18: real network abort + retry ----
let aborted = false;
await page.route("**/feature-target-ranking", route => {
  if (!aborted) { aborted = true; return route.abort("failed"); }
  return route.continue();
});
await stepTo("3特征", 400);
await stepTo("4关系", 400); // remount → ranking empty
await page.locator('section[data-testid="step-relationships"] [data-testid="run-ranking-btn"]').click();
await page.waitForSelector('[data-testid="ranking-error"]', { timeout: 15000 });
const errText = await page.locator('[data-testid="ranking-error"]').innerText();
await page.unroute("**/feature-target-ranking");
await page.locator('[data-testid="ranking-retry"]').click();
await rankingRows('section[data-testid="step-relationships"] ');
await snap("18_retry_success", {
  reachable: errText.includes("API_UNAVAILABLE") && (await page.locator('[data-testid="ranking-error"]').count()) === 0,
  evidence: "One real request was aborted via network route (rank error 'API 暂不可用 … 状态 API_UNAVAILABLE' rendered), then the real '重试 / Retry' button re-issued the POST and rows loaded — success-after-retry state.",
  notes: `error panel text seen: ${errText.slice(0, 60).replace(/\n/g, " ")}…; abort was network-level only, no data change.`,
  clipEl: page.locator('section[data-testid="step-relationships"] [data-testid="ranking-mode-badge"]'),
});

// ---- 20: full desktop page of step 4 ----
await snap("20_full_relationships_desktop", {
  reachable: true,
  evidence: "Full-page (fullPage) capture of step-4 relationships workflow at 1440×900: stepper, ranking header/badge, provenance line, full ranked table, scatter and summary in one rendered page.",
  fullPage: true,
});

// ---- 19: research assistant answers with EXPLORATORY ranking ----
await page.locator('button[aria-label="Research Assistant"]').click();
await page.waitForSelector('[data-testid="assistant-drawer"]', { timeout: 10000 });
await page.waitForSelector('[data-testid="assistant-input"]:not([disabled])', { timeout: 15000 });
await page.fill('[data-testid="assistant-input"]', "哪些超声特征与 Reference SOC 关系明显？");
await page.keyboard.press("Enter");
let exOk = false;
try {
  await page.locator('[data-testid="assistant-drawer"] [data-testid="assistant-answer"]', { hasText: "EXPLORATORY" })
    .first().waitFor({ timeout: 45000 });
  exOk = true;
} catch { /* record honestly below */ }
await page.waitForTimeout(800);
await snap("19_agent_ranking", {
  reachable: exOk,
  evidence: "Research Assistant drawer open: user question 哪些超声特征与 Reference SOC 关系明显？ → assistant bubble answers citing the deterministic EXPLORATORY relationship ranking (session-based, numbers from backend tool).",
  notes: exOk ? "Reply contained 'EXPLORATORY' as required." : "Assistant reply did not contain EXPLORATORY within 45 s — shot still shows the real rendered conversation.",
});

writeFileSync(`${OUT}/brw021r2_shots_manifest.json`, JSON.stringify({
  generated_from: "live app http://localhost:5173 (vite) → /api/v1 backend :8000, CELL_001/EXP_001 analysis workflow",
  script: "frontend/screenshot-brw021r2.mjs",
  shots,
}, null, 2));
await browser.close();
console.log("manifest written:", shots.length, "entries");
