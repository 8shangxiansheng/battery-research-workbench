# Design System — Scientific Workbench

## 技术栈

| 层 | 选择 | 说明 |
|---|---|---|
| UI 原语 | **shadcn/ui**（Radix primitives） | Button / Dialog / Sheet / Tabs / Tooltip / Popover / Command / Sidebar / Table / Skeleton / Badge / Card / Checkbox / Input / Separator |
| 样式 | **Tailwind CSS 4** | utility-first，`src/styles/workbench.css` 存放语义层（panel / eyebrow / muted / data-row 等） |
| 图标 | **Lucide** | 统一线性图标 |
| 图表 | **Plotly**（react-plotly.js factory + plotly.js-basic-dist-min） | 波形/分析图，统一主题 |
| 表格 | **TanStack Table** | Models 对比等复杂表格 |
| 字体 | **Inter**（@fontsource，400/500/600） | 正文与标题 |

## 视觉 tokens

| Token | 值 |
|---|---|
| 背景 | `#fafbfa`（off-white） |
| Surface | `#FFFFFF` |
| 文字 | near-black `#1a2420` |
| Muted | `#59666d` |
| 边框 | muted neutral `#dfe6e5` |
| 主色 | subdued slate-teal `#385c66` / `#426976`（单一 accent） |
| 成功/提示 | restrained green `#3d7a4e`、amber（draft gate `#9b782e`） |
| 圆角 | 6–8px（shadcn default `--radius`） |
| 阴影 | minimal（仅 Sheet/Dialog/Popover 浮层） |
| 密度 | medium（sidebar h-11 菜单项、panel p-5~6） |

## 语义 class（workbench.css）

`panel`（白卡）· `eyebrow`（小节导语）· `muted`（次级文字）· `data-row`（行式数据摘要）·
`finding`（科学结论高亮）· `notice`（状态提示）· `empty-state` · `scope-note` ·
`measure` / `measure-value`（BlockedValue 度量）· `skip-link`（无障碍跳转）· `assistant-trigger`。

## Plot 主题（所有 Plotly 图统一）

- `paper_bgcolor/plot_bgcolor: #fff`，grid `#edf0f0`
- 字体 Inter 12px `#59666d`，margin `{l:64,r:24,t:28,b:56}`
- 波形线 `#426976` 1.35px；gate overlay：committed `rgba(64,113,122,.09)` 实线，
  draft `rgba(162,119,47,.13)` 点线（黄=未确认）
- `displayModeBar: false`，`scrollZoom: true`，`uirevision` 绑定 frame+reset

## 禁止

neon 渐变 / glassmorphism / KPI 墙 / 重阴影 / 彩虹状态色 / 混搭多视觉库。

## 组件目录

```
src/components/ui/         shadcn 原语（不重造）
src/components/workbench/  domain 组件：
  shared.tsx               PageHeader · LoadingState · ErrorState · EmptyState ·
                           ScientificStatus · BlockedValue · ScopeNote
  ParameterDialog.tsx      采样率录入 Dialog（含 provenance source 必填）
  WaveformPlot.tsx         Plotly 波形 + gate overlay + drag select
src/components/scientific/ 科学展示组件（FeatureCard / MetricComparison 等内联于页面，
                           抽取随使用密度演进）
src/lib/presentation.ts    displayName（友好名映射）· numberText（数字格式化）·
                           modelComparison（Dummy 对比，仅比较 API 已提供结果）
```
