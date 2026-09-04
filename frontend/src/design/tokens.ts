/** BRW-025R Scientific Workbench Design System — design tokens (§20). */

export const tokens = {
  color: {
    background: "#F7F8FA",
    surface: "#FFFFFF",
    border: "#D9DEE7",
    text: "#1F2937",
    muted: "#667085",
    primary: "#2C4A6E",
    primarySoft: "#E3EBF4",
    success: "#3D7A4E",
    successSoft: "#E7F2EA",
    warning: "#9A6A0B",
    warningSoft: "#FBF3DF",
    blocked: "#A0453E",
    blockedSoft: "#F9ECEA",
    info: "#44587A",
    infoSoft: "#E9EEF6",
    mono: "'SF Mono', 'Menlo', 'Consolas', monospace",
  },
  radius: { sm: 4, md: 6, lg: 8 },
  spacing: (n: number): string => `${n * 4}px`,
  fontSize: { sm: 12, base: 13, lg: 15, xl: 18 },
} as const;

export const CSS_VARS = `
:root {
  --bg: ${tokens.color.background};
  --surface: ${tokens.color.surface};
  --border: ${tokens.color.border};
  --text: ${tokens.color.text};
  --muted: ${tokens.color.muted};
  --primary: ${tokens.color.primary};
  --primary-soft: ${tokens.color.primarySoft};
  --success: ${tokens.color.success};
  --success-soft: ${tokens.color.successSoft};
  --warning: ${tokens.color.warning};
  --warning-soft: ${tokens.color.warningSoft};
  --blocked: ${tokens.color.blocked};
  --blocked-soft: ${tokens.color.blockedSoft};
  --info: ${tokens.color.info};
  --info-soft: ${tokens.color.infoSoft};
  --radius: ${tokens.radius.md}px;
  --radius-lg: ${tokens.radius.lg}px;
  --font-mono: ${tokens.color.mono};
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: ${tokens.fontSize.base}px;
  line-height: 1.55;
}
code, .mono { font-family: var(--font-mono); font-size: 0.92em; }
h1, h2, h3, h4 { margin: 0.4em 0 0.3em; font-weight: 600; }
h2 { font-size: ${tokens.fontSize.xl}px; }
h3 { font-size: ${tokens.fontSize.lg}px; }
a { color: var(--primary); }
button {
  font: inherit;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  border-radius: var(--radius);
  padding: 5px 12px;
  cursor: pointer;
}
button:hover { background: var(--primary-soft); }
button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}
button.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
button.primary:hover { filter: brightness(1.08); background: var(--primary); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
input, select, textarea {
  font: inherit;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 5px 8px;
  background: var(--surface);
  color: var(--text);
}
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 600; font-size: ${tokens.fontSize.sm}px; }
`;
