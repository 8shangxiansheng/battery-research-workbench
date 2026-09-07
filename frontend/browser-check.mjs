import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message.slice(0, 200)));
const checks = [
  ['/', '实验库'],
  ['/experiments/CELL_001/EXP_001/overview', '总览'],
  ['/experiments/CELL_001/EXP_001/waveform', '波形与闸门'],
  ['/experiments/CELL_001/EXP_001/analysis', '特征分析'],
  ['/experiments/CELL_001/EXP_001/models', 'SOC 建模'],
  ['/experiments/CELL_001/EXP_001/report', '科学报告'],
  ['/experiments/CELL_001/EXP_001/advanced/parameters', '科学参数'],
];
for (const [url, expect] of checks) {
  await page.goto('http://localhost:5173' + url, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(1800);
  const text = await page.locator('body').innerText();
  console.log(url, '→', text.includes(expect) ? '✓ ' + expect : '✗ 缺少 ' + expect);
}
console.log('errors:', errors.length ? errors : '无');
await browser.close();
