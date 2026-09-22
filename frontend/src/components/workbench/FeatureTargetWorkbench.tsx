import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { ApiError, client, type FeatureRankingEntry, type FeatureRankingResponse, type RankingDetail } from "../../api/client";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from "../ui/table";
import { LoadingState } from "./shared";
import { numberText } from "../../lib/presentation";
import { TARGET_LABELS } from "./FeatureLabelTable";

/** BRW-021R2 §22 — typed failure taxonomy replacing the generic view error. */
export type RankingErrorKind =
  | "RELATIONSHIP_ARTIFACT_MISSING" | "STALE_ANALYSIS" | "API_UNAVAILABLE"
  | "TARGET_NOT_READY" | "NO_ELIGIBLE_FEATURES" | "INVALID_SPLIT" | "UNEXPECTED_ERROR";

export function classifyRankingError(err: unknown): { kind: RankingErrorKind; detail: string } {
  const msg = err instanceof ApiError ? `${err.code} ${err.message}` : String(err ?? "");
  if (/INVALID_SPLIT|split assignments|requires split_id/i.test(msg)) return { kind: "INVALID_SPLIT", detail: msg };
  if (/ARTIFACT_NOT_AVAILABLE|not materialized|RELATIONSHIP_ARTIFACT_MISSING/i.test(msg)) return { kind: "RELATIONSHIP_ARTIFACT_MISSING", detail: msg };
  if (/SOURCE_MOVMEAN5/i.test(msg)) return { kind: "STALE_ANALYSIS", detail: msg };
  if (/unknown target|TARGET/i.test(msg) && /ready|unknown target/i.test(msg)) return { kind: "TARGET_NOT_READY", detail: msg };
  if (/unknown features|VALIDATION_ERROR/i.test(msg)) return { kind: "NO_ELIGIBLE_FEATURES", detail: msg };
  if (/Failed to fetch|NetworkError|timeout/i.test(msg)) return { kind: "API_UNAVAILABLE", detail: msg };
  return { kind: "UNEXPECTED_ERROR", detail: msg };
}

const ERROR_COPY: Record<RankingErrorKind, string> = {
  RELATIONSHIP_ARTIFACT_MISSING: "关系分析工件缺失 — 需先通过正式工作流生成（这不是网络错误）。",
  STALE_ANALYSIS: "该分析已过期或仅限探索 — 请刷新特征定义后重试。",
  API_UNAVAILABLE: "API 暂不可用 — 请确认后端服务后点击重试。",
  TARGET_NOT_READY: "所选目标当前不可评估 — 请检查目标 readiness。",
  NO_ELIGIBLE_FEATURES: "没有可排名的特征 — 请先在特征页勾选有效特征。",
  INVALID_SPLIT: "ML-safe 排名需要有效的 Grouped Split（split_id + fold）。",
  UNEXPECTED_ERROR: "未预期的错误 — 重试后如仍失败请查看支持信息。",
};

const DIRECTION_LABEL: Record<string, string> = {
  SAME_DIRECTION: "方向一致", DIRECTION_DEPENDENT: "方向依赖",
  WEAK_ASSOCIATION: "弱关联", INSUFFICIENT_VARIATION: "变化不足", UNAVAILABLE: "不可用",
};

function DirectionBadge({ entry }: { entry: FeatureRankingEntry }) {
  const dir = entry.direction_status ?? (entry.direction_dependent ? "DIRECTION_DEPENDENT" : "SAME_DIRECTION");
  const variant = dir === "DIRECTION_DEPENDENT" ? "outline" : dir === "SAME_DIRECTION" ? "secondary" : "outline";
  return <Badge variant={variant as "outline" | "secondary"} data-testid={`direction-${entry.feature_code}`}>
    {dir === "DIRECTION_DEPENDENT" && <TriangleAlert size={11} className="mr-1" />}
    {DIRECTION_LABEL[dir] ?? dir}</Badge>;
}

/** §13 relationship detail: backend-provided scatter, frontend never computes. */
function ScatterPanel({ detail }: { detail: RankingDetail }) {
  const scopes = Object.keys(detail.scopes ?? {});
  const [scope, setScope] = useState(scopes.includes("overall") ? "overall" : scopes[0] ?? "overall");
  const pts = detail.scopes?.[scope]?.points ?? [];
  const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const sx = (v: number) => 8 + ((v - x0) / (x1 - x0 || 1)) * 304;
  const sy = (v: number) => 192 - ((v - y0) / (y1 - y0 || 1)) * 184;
  return <div className="panel p-4 mt-4" data-testid="relationship-detail">
    <div className="flex items-center gap-3 flex-wrap">
      <h4 className="font-medium">关系散点 / Relationship scatter — {detail.feature_code}</h4>
      {scopes.map(s => <Button key={s} size="sm" variant={s === scope ? "default" : "outline"}
        onClick={() => setScope(s)} data-testid={`scatter-scope-${s}`}>{s}</Button>)}
      <span className="text-xs muted ml-auto">n={detail.scopes?.[scope]?.n ?? 0} · 后端计算，前端不重算</span>
    </div>
    <svg width={320} height={200} className="mt-2 border rounded bg-white" role="img"
      aria-label={`${detail.feature_code} 与 ${detail.target_id} 的 ${scope} 散点图`}>
      <line x1={8} y1={196} x2={316} y2={196} stroke="#999" />
      <line x1={8} y1={4} x2={8} y2={196} stroke="#999" />
      {pts.map((p, i) => <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={1.6} fill="#2f7d6d" opacity={0.6} />)}
    </svg>
    <p className="text-xs muted mt-1">x = {detail.feature_code} · y = {TARGET_LABELS[detail.target_id] ?? detail.target_id}
      {detail.excluded_ineligible != null && <> · excluded (ineligible) {detail.excluded_ineligible}</>}</p>
  </div>;
}

type SortKey = "display" | "abs_pearson" | "abs_charge" | "abs_discharge" | "name" | "family" | "coverage";

/** Feature × Target ranking (BRW-021R2). Exploratory = all eligible rows,
 *  explicitly Not ML-safe; TRAIN_ONLY = fold TRAIN rows only (structural). */
export function FeatureRankingTable({ batteryId, experimentId, targetId, features, mode,
  splitId, foldIndex, selected, onSelectedChange }: {
  batteryId: string; experimentId: string; targetId: string; features: string[];
  mode: "EXPLORATORY" | "TRAIN_ONLY_ML_SAFE";
  splitId?: string; foldIndex?: string;
  selected?: string[]; onSelectedChange?: (codes: string[], source: string) => void;
}) {
  const [sortBy, setSortBy] = useState<SortKey>("display");
  
  const rank = useMutation({
    mutationFn: () => client.postFeatureTargetRanking(batteryId, experimentId, {
      target_id: targetId, features, mode,
      ...(mode === "TRAIN_ONLY_ML_SAFE" ? { split_id: splitId, fold_index: foldIndex } : {}),
    }),
  });
  const detailMut = useMutation({
    mutationFn: (code: string) => client.postFeatureTargetRanking(batteryId, experimentId, {
      target_id: targetId, features: [code, ...features.filter(f => f !== code)].slice(0, 12), mode,
      ...(mode === "TRAIN_ONLY_ML_SAFE" ? { split_id: splitId, fold_index: foldIndex } : {}),
      detail_feature: code,
    }),
  });
  const isSoh = targetId === "soh_capacity_reference_percent";
  const isDirect = targetId === "voltage_v" || targetId === "current_a";
  const d: FeatureRankingResponse | undefined = rank.data?.data ?? undefined;
  const rows = useMemo(() => {
    const r = [...(d?.ranking ?? [])];
    const key = (e: FeatureRankingEntry) => {
      switch (sortBy) {
        case "abs_pearson": return -Math.abs(e.pearson_overall ?? e.pearson ?? 0);
        case "abs_charge": return -Math.abs(e.spearman_charge ?? e.pearson_charge ?? 0);
        case "abs_discharge": return -Math.abs(e.spearman_discharge ?? e.pearson_discharge ?? 0);
        case "name": return e.feature_code;
        case "family": return e.family ?? "ZZZ";
        case "coverage": return -(e.n_valid ?? 0);
        default: return -Math.abs(e.spearman_overall ?? 0);
      }
    };
    return r.sort((a, b) => { const ka = key(a), kb = key(b); return typeof ka === "string" ? String(ka).localeCompare(String(kb)) : (ka as number) - (kb as number); });
  }, [d, sortBy]);
  const err = rank.error ? classifyRankingError(rank.error) : null;
  const toggle = (code: string) => {
    if (!onSelectedChange) return;
    const next = (selected ?? []).includes(code) ? (selected ?? []).filter(c => c !== code) : [...(selected ?? []), code];
    onSelectedChange(next, mode === "TRAIN_ONLY_ML_SAFE" ? "TRAIN_ONLY_RELATIONSHIP_RANKING" : "EXPLORATORY_RELATIONSHIP_RANKING");
  };
  return <div data-testid="feature-ranking">
    <div className="flex flex-wrap gap-3 items-center">
      <Button onClick={() => { rank.mutate(); }} disabled={!features.length || rank.isPending}
        data-testid="run-ranking-btn">
        {rank.isPending ? "正在分析… / Ranking…" : "Rank features / 特征排序"}</Button>
      <Badge variant={mode === "EXPLORATORY" ? "outline" : "secondary"} data-testid="ranking-mode-badge">
        {mode === "EXPLORATORY" ? "EXPLORATORY · 非 ML-safe" : "TRAIN-ONLY ML-SAFE"}</Badge>
      {mode === "TRAIN_ONLY_ML_SAFE" && foldIndex && <Badge variant="outline" data-testid="ranking-fold-badge">{foldIndex} · TRAIN rows only</Badge>}
      <span className="text-sm muted">Target (y): <strong>{TARGET_LABELS[targetId] ?? targetId}</strong></span>
      {d && <select aria-label="显示排序" data-testid="ranking-sort" className="text-sm border rounded px-2 py-1 ml-auto"
        value={sortBy} onChange={e => setSortBy(e.target.value as SortKey)}>
        <option value="display">Default display ordering (|Spearman overall|)</option>
        <option value="abs_pearson">|Pearson overall|</option>
        <option value="abs_charge">|Charge Spearman|</option>
        <option value="abs_discharge">|Discharge Spearman|</option>
        <option value="name">Feature name</option>
        <option value="family">Family</option>
        <option value="coverage">Valid coverage</option>
      </select>}
    </div>
    <p className="text-xs muted mt-2">Ranking 仅描述统计关联：不代表因果关系、不保证预测能力、不指“科学最优”。 / Higher association does not imply causation or guaranteed predictive value.</p>
    {features.length > 12 && <p className="text-xs text-[#9b782e] mt-1" data-testid="ranking-cap-note">已选 {features.length} 个特征 — 后端最多对前 12 个做 ranking（超出部分未参与）。</p>}
    {rank.isPending && <LoadingState />}
    {err && <div role="alert" className="notice mt-3" data-testid="ranking-error">
      <p className="font-medium">{ERROR_COPY[err.kind]}</p>
      <p className="text-xs mt-1">状态 {err.kind}{err.detail ? ` · ${err.detail.slice(0, 160)}` : ""}</p>
      <Button variant="outline" className="mt-3" size="sm" data-testid="ranking-retry"
        onClick={() => rank.mutate()}>重试 / Retry（真实重新请求）</Button>
    </div>}
    {d && (d.alias_dedup?.length ?? 0) > 0 && <p className="text-xs muted mt-2" data-testid="alias-dedup-note">
      别名去重：{d.alias_dedup!.map(a => `${a.dropped} ≡ ${a.kept}`).join(" · ")}（同一序列只排名一次）</p>}
    {d && (d.blocked_forbidden?.length ?? 0) > 0 && <p className="text-xs text-[#9b782e] mt-2" data-testid="forbidden-blocked">
      已按目标泄漏策略 BLOCK（不排名、不可提交）：{d.blocked_forbidden!.map(b => b.feature_code).join(", ")}</p>}
    {d && !isSoh && d.ranking.length === 0 && !err && <p className="text-sm muted mt-3" data-testid="ranking-empty">NO_ELIGIBLE_FEATURES — 当前范围内没有可排名特征。</p>}
    {d && isSoh && d.group_summary && <div className="mt-4" data-testid="soh-group-summary">
      <p className="text-sm flex gap-2 items-center"><TriangleAlert size={15} className="text-[#9b782e]" />
        仅 {new Set(d.group_summary.map(g => g.soh_percent)).size} 个独立 SOH 状态 — Limited，不做 frame 级相关性结论。</p>
      <Table className="mt-3"><TableHeader><TableRow><TableHead>Cycle</TableHead><TableHead>SOH</TableHead><TableHead>n frames</TableHead><TableHead>Feature mean</TableHead><TableHead>Median</TableHead><TableHead>Std</TableHead></TableRow></TableHeader>
        <TableBody>{d.group_summary.map(g => <TableRow key={g.cycle}><TableCell>{g.cycle}</TableCell><TableCell>{numberText(g.soh_percent, 2)}</TableCell><TableCell>{g.n_frames}</TableCell><TableCell>{numberText(g.feature_mean, 1)}</TableCell><TableCell>{numberText(g.feature_median, 1)}</TableCell><TableCell>{numberText(g.feature_std, 1)}</TableCell></TableRow>)}</TableBody></Table>
    </div>}
    {d && d.tof_provenance && <p className="text-xs muted mt-2" data-testid="ranking-tof-provenance">
      canonical TOF：{d.tof_provenance.canonical_method ?? (d.tof_provenance as { tof_method_id?: string }).tof_method_id} ·
      fs {d.tof_provenance.fs_hz ? `${Number(d.tof_provenance.fs_hz) / 1e6} MHz (verified)` : (d.tof_provenance as { sampling_rate_hz?: number }).sampling_rate_hz ? `${Number((d.tof_provenance as { sampling_rate_hz?: number }).sampling_rate_hz) / 1e6} MHz (verified)` : "未验证"} ·
      gate {d.tof_provenance.gate_calibration_id}（artifact 取值来源；当前已确认 {d.tof_provenance.current_gate_calibration_id} v{d.tof_provenance.current_gate_calibration_version}，{d.tof_provenance.gate_calibration_window_matches_current ? "窗口一致" : <strong>窗口已变化 · Refresh required</strong>}） ·
      waveform valid {(d.tof_provenance as { waveform_valid_rows?: number }).waveform_valid_rows ?? "—"} / target eligible {d.summary?.target_eligible_rows ?? "—"}</p>}
    {d && rows.length > 0 && <Table className="mt-4">
      <TableHeader><TableRow>
        <TableHead>#</TableHead><TableHead>Feature / 特征</TableHead><TableHead>Family</TableHead><TableHead>Units</TableHead>
        <TableHead>n valid / missing</TableHead>
        <TableHead>Pearson</TableHead><TableHead>Spearman</TableHead>
        {!isDirect && !isSoh && <><TableHead>Charge ρ</TableHead><TableHead>Discharge ρ</TableHead><TableHead>Direction</TableHead></>}
        <TableHead>Status</TableHead>{onSelectedChange && <TableHead>Select</TableHead>}
      </TableRow></TableHeader>
      <TableBody>{rows.map((r, i) => <TableRow key={r.feature_code} data-testid={`rank-${r.feature_code}`}>
        <TableCell className="tabular-nums">{i + 1}</TableCell>
        <TableCell className="font-medium">
          <button className="text-left underline-offset-2 hover:underline" data-testid={`detail-${r.feature_code}`}
            onClick={() => detailMut.mutate(r.feature_code)}>{r.label_zh ?? r.feature_code}
            <span className="muted text-xs ml-1">{r.feature_code}</span></button>
          {r.legacy_diagnostic && <Badge variant="outline" className="ml-1 text-xs">诊断量</Badge>}
          {r.exploratory_only && <Badge variant="outline" className="ml-1 text-xs">仅探索</Badge>}
        </TableCell>
        <TableCell className="text-xs">{r.family ?? "—"}</TableCell>
        <TableCell className="text-xs">{r.units ?? "—"}</TableCell>
        <TableCell className="tabular-nums">{r.n_valid ?? "—"} / {r.n_missing ?? "—"}</TableCell>
        <TableCell className="tabular-nums">{numberText(r.pearson_overall ?? r.pearson, 3)}</TableCell>
        <TableCell className="tabular-nums">{numberText(r.spearman_overall ?? r.spearman, 3)}</TableCell>
        {!isDirect && !isSoh && <>
          <TableCell className="tabular-nums">{numberText(r.spearman_charge ?? r.pearson_charge, 3)}</TableCell>
          <TableCell className="tabular-nums">{numberText(r.spearman_discharge ?? r.pearson_discharge, 3)}</TableCell>
          <TableCell><DirectionBadge entry={r} /></TableCell></>}
        <TableCell>{r.status === "VALID" ? <Badge variant="secondary">VALID</Badge> : <Badge variant="outline" data-testid={`rank-status-${r.feature_code}`}>{r.status}</Badge>}</TableCell>
        {onSelectedChange && <TableCell><input type="checkbox" aria-label={`选择 ${r.feature_code}`}
          data-testid={`select-${r.feature_code}`}
          disabled={r.commit_eligible === false}
          checked={(selected ?? []).includes(r.feature_code)}
          onChange={() => toggle(r.feature_code)} /></TableCell>}
      </TableRow>)}</TableBody>
    </Table>}
    {detailMut.data?.data?.detail && <ScatterPanel detail={detailMut.data.data.detail} />}
    {d?.summary && <p className="text-xs muted mt-2" data-testid="ranking-summary">
      aligned {d.summary.aligned_events} · target-eligible {d.summary.target_eligible_rows} ·
      mode {d.mode}{d.limitations ? ` · ${d.limitations.join(" · ")}` : ""}</p>}
  </div>;
}
