/** BRW-025R Design System primitives: Card / Badge / Stepper / Collapse / Drawer / EmptyState. */
import type { CSSProperties, ReactElement, ReactNode } from "react";
import { tokens } from "./tokens";

export function Card({
  title,
  actions,
  children,
  style,
  testId,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  style?: CSSProperties;
  testId?: string;
}): ReactElement {
  return (
    <section
      data-testid={testId}
      style={{
        background: tokens.color.surface,
        border: `1px solid ${tokens.color.border}`,
        borderRadius: tokens.radius.lg,
        padding: "14px 16px",
        marginBottom: 12,
        ...style,
      }}
    >
      {(title || actions) && (
        <header style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          {title ? <h3 style={{ margin: 0, flex: 1 }}>{title}</h3> : <span style={{ flex: 1 }} />}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

type BadgeTone = "neutral" | "primary" | "success" | "warning" | "blocked" | "info";

const TONE_MAP: Record<BadgeTone, { bg: string; fg: string }> = {
  neutral: { bg: tokens.color.background, fg: tokens.color.muted },
  primary: { bg: tokens.color.primarySoft, fg: tokens.color.primary },
  success: { bg: tokens.color.successSoft, fg: tokens.color.success },
  warning: { bg: tokens.color.warningSoft, fg: tokens.color.warning },
  blocked: { bg: tokens.color.blockedSoft, fg: tokens.color.blocked },
  info: { bg: tokens.color.infoSoft, fg: tokens.color.info },
};

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }): ReactElement {
  const t = TONE_MAP[tone];
  return (
    <span
      style={{
        background: t.bg,
        color: t.fg,
        borderRadius: 999,
        padding: "1px 10px",
        fontSize: tokens.fontSize.sm,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

export function Stepper({ steps, current }: { steps: string[]; current: number }): ReactElement {
  return (
    <ol data-testid="pipeline-stepper" style={{ display: "flex", flexWrap: "wrap", gap: 4, listStyle: "none", padding: 0, margin: 0 }}>
      {steps.map((s, i) => {
        const state = i < current ? "done" : i === current ? "active" : "todo";
        const bg = state === "done" ? tokens.color.successSoft : state === "active" ? tokens.color.primarySoft : tokens.color.background;
        const fg = state === "done" ? tokens.color.success : state === "active" ? tokens.color.primary : tokens.color.muted;
        return (
          <li key={s} style={{ background: bg, color: fg, borderRadius: tokens.radius.sm, padding: "2px 9px", fontSize: tokens.fontSize.sm }}>
            {i < current ? "✓ " : ""}
            {s}
          </li>
        );
      })}
    </ol>
  );
}

export function Collapse({ summary, children, testId, defaultOpen = false }: {
  summary: ReactNode;
  children: ReactNode;
  testId?: string;
  defaultOpen?: boolean;
}): ReactElement {
  return (
    <details data-testid={testId} open={defaultOpen}>
      <summary style={{ cursor: "pointer", color: tokens.color.muted }}>{summary}</summary>
      <div style={{ paddingTop: 8 }}>{children}</div>
    </details>
  );
}

export function Drawer({ title, onClose, children }: { title: ReactNode; onClose: () => void; children: ReactNode }): ReactElement {
  return (
    <div
      role="dialog"
      aria-label={typeof title === "string" ? title : "detail panel"}
      style={{
        position: "fixed",
        top: 0,
        right: 0,
        width: 420,
        maxWidth: "90vw",
        height: "100vh",
        background: tokens.color.surface,
        borderLeft: `1px solid ${tokens.color.border}`,
        boxShadow: "-8px 0 24px rgba(0,0,0,0.08)",
        padding: 16,
        overflowY: "auto",
        zIndex: 50,
      }}
    >
      <header style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, flex: 1 }}>{title}</h3>
        <button type="button" aria-label="关闭面板" onClick={onClose}>×</button>
      </header>
      {children}
    </div>
  );
}

export function EmptyState({ title, actions }: { title: ReactNode; actions?: ReactNode }): ReactElement {
  return (
    <div
      style={{
        textAlign: "center",
        padding: "64px 16px",
        background: tokens.color.surface,
        border: `1px dashed ${tokens.color.border}`,
        borderRadius: tokens.radius.lg,
      }}
    >
      <p style={{ fontSize: tokens.fontSize.xl, fontWeight: 600 }}>{title}</p>
      <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>{actions}</div>
    </div>
  );
}

export function StatusText({ children }: { children: ReactNode }): ReactElement {
  return <p role="status">{children}</p>;
}
