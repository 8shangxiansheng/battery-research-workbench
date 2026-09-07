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
  return <div role="status" aria-label="加载中" className="space-y-6"><span className="sr-only">加载中…</span><Skeleton className="h-10 w-64"/><Skeleton className="h-24 w-full"/><Skeleton className="h-64 w-full"/></div>;
}
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return <div role="alert" className="notice"><Info size={18}/><div><h3>无法加载此视图</h3><p>请检查连接后重试。实验数据不受影响。</p>{error instanceof ApiError && <details><summary>支持信息</summary><p>错误码 {error.code} · 请求 {error.requestId}</p></details>}{retry && <Button variant="outline" className="mt-3" onClick={retry}><RotateCcw/>重试</Button>}</div></div>;
}
export function EmptyState({ title, children, to, action }: { title: string; children: ReactNode; to?: string; action?: string }) {
  return <div className="empty-state"><CircleHelp className="mb-5 text-slate-500" size={32}/><h2>{title}</h2><p className="muted max-w-md my-3">{children}</p>{to && <Button asChild className="mt-3"><Link to={to}>{action ?? "前往特征分析"}<ArrowRight/></Link></Button>}</div>;
}
export function ScientificStatus({ value }: { value: string }) { return <Badge variant="secondary">{displayName(value)}</Badge>; }
export function BlockedValue({ name, value, unit, reason, action }: { name: string; value?: unknown; unit?: string; reason?: string; action?: ReactNode }) {
  return <div className="measure"><p className="muted text-sm">{name}</p><p className="measure-value">{numberText(value)} <span>{typeof value === "number" ? unit : ""}</span></p>{reason && <p className="text-sm muted">{reason}</p>}{action && <div className="mt-3">{action}</div>}</div>;
}
export function ScopeNote() { return <p className="scope-note"><Info size={15}/>参考 SOC · 有限评估 · 结果仅针对当前实验。</p>; }
