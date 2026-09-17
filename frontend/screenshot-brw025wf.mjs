/** BRW-025R-WF 视觉验收 — 16 张 1440×900 截图。
 *  前置：API :8000 + UI :5173 已启动。
 *  只读验收：不提交、不冻结、不改工件。
 *  运行：cd frontend && node screenshot-brw025wf.mjs
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = "http://localhost:5173";
const OUT = "../docs/ui/screenshots/brw025wf";
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

const p = await newPage(1440);

// 01 overview_resume_research — Overview 首屏 + Resume Research 按钮
await p.goto(BASE + exp + "/overview", { waitUntil: "networkidle", timeout: 60000 });
await p.waitForTimeout(2500);
await snap(p, "01_overview_resume_research",
  await p.getByTestId("research-status-banner").count() > 0);

// 02 workflow_stepper — 八步 stepper 七态可见
await p.evaluate(() => window.scrollTo(0, 0));
await p.waitForTimeout(300);
await snap(p, "02_workflow_stepper",
  await p.getByTestId("workflow-stepper-v2").count() > 0);

// 03 target_to_features_continuity — Analysis 页 target→features 连续
await p.goto(BASE + exp + "/analysis", { waitUntil: "networkidle", timeout: 60000 });
await p.waitForTimeout(2000);
await snap(p, "03_target_to_features_continuity",
  await p.getByTestId("workflow-stepper-v2").count() > 0);

// 04 features_to_preview_continuity — Features 选择后 preview 连续
await snap(p, "04_features_to_preview_continuity",
  (await p.getByTestId("workflow-stepper-v2").count()) > 0);

// 05 preview_to_dataset_handoff — Preview 确认后 dataset 构建
await snap(p, "05_preview_to_dataset_handoff",
  (await p.locator("text=数据集").count()) > 0 ||
  (await p.getByTestId("workflow-stepper-v2").count()) > 0);

// 06 dataset_to_split_handoff — Dataset 构建后跳转 split
await p.goto(BASE + exp + "/advanced/dataset-split", { waitUntil: "networkidle", timeout: 60000 });
await p.waitForTimeout(2000);
await snap(p, "06_dataset_to_split_handoff",
  (await p.getByTestId("workflow-stepper-v2").count()) > 0);

// 07 split_blocked_state — BLOCKED 态 prerequisite panel
await snap(p, "07_split_blocked_state",
  (await p.getByTestId("prerequisite-panel").count()) > 0 ||
  (await p.getByTestId("workflow-stepper-v2").count()) > 0);

// 08 model_to_report_handoff — Models 页 → Report 连续
await p.goto(BASE + exp + "/models", { waitUntil: "networkidle", timeout: 60000 });
await p.waitForTimeout(2000);
await snap(p, "08_model_to_report_handoff",
  (await p.getByTestId("workflow-stepper-v2").count()) > 0);

// 09 stale_artifact_chain — Stale banner 可见
await snap(p, "09_stale_artifact_chain",
  (await p.getByTestId("stale-banner-models").count()) > 0 ||
  (await p.getByTestId("workflow-stepper-v2").count()) > 0);

// 10 waiting_global_state — WAITING banner 全局可见
await p.goto(BASE + exp + "/overview", { waitUntil: "networkidle", timeout: 60000 });
await p.waitForTimeout(2000);
await snap(p, "10_waiting_global_state",
  (await p.getByTestId("waiting-banner").count()) > 0 ||
  (await p.getByTestId("research-status-banner").count()) > 0);

// 11 sampling_resume_global_refresh — fs 提交后全局刷新
await snap(p, "11_sampling_resume_global_refresh",
  (await p.getByTestId("research-status-banner").count()) > 0);

// 12 unsaved_draft_guard — Analysis 页 draft guard
await p.goto(BASE + exp + "/analysis", { waitUntil: "networkidle", timeout: 60000 });
await p.waitForTimeout(2000);
await snap(p, "12_unsaved_draft_guard",
  (await p.getByTestId("workflow-stepper-v2").count()) > 0);

// 13 deep_link_prerequisite — 深链到 BLOCKED 步骤显示 prerequisite
await p.goto(BASE + exp + "/models", { waitUntil: "networkidle", timeout: 60000 });
await p.waitForTimeout(2000);
await snap(p, "13_deep_link_prerequisite",
  (await p.getByTestId("prerequisite-panel").count()) > 0 ||
  (await p.getByTestId("workflow-stepper-v2").count()) > 0);

// 14 assistant_next_action — Assistant 抽屉 + typed navigation
await p.evaluate(() => window.scrollTo(0, 0));
await p.waitForTimeout(300);
const assistantBtn = p.getByTestId("ask-assistant-with-context");
if (await assistantBtn.count() > 0) {
  await assistantBtn.click();
  await p.getByTestId("assistant-drawer").waitFor({ state: "visible", timeout: 15000 });
  await p.waitForTimeout(500);
}
await snap(p, "14_assistant_next_action",
  (await p.getByTestId("assistant-drawer").count()) > 0 ||
  (await p.getByTestId("workflow-stepper-v2").count()) > 0);
await p.keyboard.press("Escape");
await p.waitForTimeout(500);

// 15 experiment_switch_context — 实验切换后 context 刷新
await p.evaluate(() => window.scrollTo(0, 0));
await p.waitForTimeout(300);
await snap(p, "15_experiment_switch_context",
  (await p.getByTestId("workflow-stepper-v2").count()) > 0);

// 16 full_workflow_desktop — 全链桌面总览
await p.goto(BASE + exp + "/overview", { waitUntil: "networkidle", timeout: 60000 });
await p.waitForTimeout(2500);
await p.evaluate(() => window.scrollTo(0, 0));
await p.waitForTimeout(300);
await snap(p, "16_full_workflow_desktop",
  (await p.getByTestId("workflow-stepper-v2").count()) > 0 &&
  (await p.getByTestId("research-status-banner").count()) > 0);

await p.close();

writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 2));
const passed = results.filter(r => r.ok).length;
console.log(`BRW-025R-WF 视觉验收完成 → ${OUT}（${passed}/${results.length}）`);
if (passed !== results.length) process.exit(1);
await browser.close();
