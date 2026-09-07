import type { ReactNode } from "react";
import { ArrowRight, CircleHelp, Info, RotateCcw } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Skeleton } from "../ui/skeleton";
import { ApiError } from "../../api/client";
import { displayName, numberText } from "../../lib/presentation";

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  return <header className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="muted leading-relaxed">{description}</p></div>{actions}</header>;
}
export function LoadingState() {
  return <div role="status" aria-label="Loading workbench" className="space-y-6"><span className="sr-only">Loading…</span><Skeleton className="h-10 w-64"/><Skeleton className="h-24 w-full"/><Skeleton className="h-64 w-full"/></div>;
}
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return <div role="alert" className="notice"><Info size={18}/><div><h3>We couldn’t load this view</h3><p>Check the connection and try again. Your experiment is unchanged.</p>{error instanceof ApiError && <details><summary>Support details</summary><p>{error.code} · request {error.requestId}</p></details>}{retry && <Button variant="outline" className="mt-3" onClick={retry}><RotateCcw/>Retry</Button>}</div></div>;
}
export function EmptyState({ title, children, to, action }: { title: string; children: ReactNode; to?: string; action?: string }) {
  return <div className="empty-state"><CircleHelp className="mb-5 text-slate-500" size={32}/><h2>{title}</h2><p className="muted max-w-md my-3">{children}</p>{to && <Button asChild className="mt-3"><Link to={to}>{action ?? "Go to Analysis"}<ArrowRight/></Link></Button>}</div>;
}
export function ScientificStatus({ value }: { value: string }) { return <Badge variant="secondary">{displayName(value)}</Badge>; }
export function BlockedValue({ name, value, unit, reason, action }: { name: string; value?: unknown; unit?: string; reason?: string; action?: ReactNode }) {
  return <div className="measure"><p className="muted text-sm">{name}</p><p className="measure-value">{numberText(value)} <span>{typeof value === "number" ? unit : ""}</span></p>{reason && <p className="text-sm muted">{reason}</p>}{action && <div className="mt-3">{action}</div>}</div>;
}
export function ScopeNote() { return <p className="scope-note"><Info size={15}/>Reference SOC · Limited evaluation · Results are specific to this experiment.</p>; }
