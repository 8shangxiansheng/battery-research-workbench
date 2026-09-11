import { useMutation } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Eye, EyeOff, Info, RefreshCw } from "lucide-react";
import { client, type FeatureLabelPreviewRow, type FeatureLabelPreviewResponse, type FeatureMetaEntry } from "../../api/client";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../ui/dialog";
import { Input } from "../ui/input";
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from "../ui/table";
import { LoadingState, ErrorState } from "./shared";
import { numberText } from "../../lib/presentation";

export const FEATURE_LABELS: Record<string, string> = {
  SWA: "SWA / 表面波幅值", BOTTOM_AMP: "Bottom-wave Amplitude / 底波幅值",
  TOF_XCORR: "XCorr TOF / 互相关TOF（诊断）", ATTEN_MAX: "Attenuation max / 衰减最大",
  ATTEN_MEAN: "Attenuation mean / 衰减平均", ATTEN_ENERGY: "Attenuation energy / 衰减能量",
  BPS: "BPS / 底波相移",
  amplitude_a_u: "Amplitude / 幅值（核心别名）",
};
export const TARGET_LABELS: Record<string, string> = {
  reference_soc_percent: "Reference SOC / 参考 SOC",
  temperature_c: "Temperature / 温度",
  soh_capacity_reference_percent: "SOH / 健康状态",
  voltage_v: "Voltage / 电压",
  current_a: "Current / 电流",
};
const STATE_ZH: Record<string, string> = { charge: "充电", discharge: "放电", rest: "静置" };
const PAGE_SIZE = 50;

export function EligibilityBreakdown({ summary }: { summary: FeatureLabelPreviewResponse["summary"] }) {
  const funnel = [
    { label: "Raw ultrasound frames / 原始超声帧", value: summary.total_frames, testid: "funnel-raw" },
    { label: "Aligned events / 已对齐事件", value: summary.aligned_events, testid: "funnel-aligned" },
    { label: "Target-valid rows / 目标有效行", value: summary.aligned_events - (summary.excluded_by_reason["TARGET_MISSING"] ?? 0) - (summary.excluded_by_reason["AMBIGUOUS_SYNC"] ?? 0), testid: "funnel-target-valid" },
    { label: "Feature-complete rows / 特征完整行", value: summary.aligned_events - (summary.excluded_by_reason["FEATURE_MISSING"] ?? 0), testid: "funnel-feature-complete" },
    { label: "Final eligible rows / 最终可分析行", value: summary.eligible_rows, testid: "funnel-eligible" },
  ];
  const breakdown = [
    { label: "歧义同步 / Ambiguous", key: "AMBIGUOUS_SYNC" },
    { label: "未匹配 / Unmatched", key: "UNMATCHED_SYNC" },
    { label: "目标缺失 / Target missing", key: "TARGET_MISSING" },
    { label: "特征缺失 / Feature missing", key: "FEATURE_MISSING" },
    { label: "分析不可用 / Ineligible", key: "ANALYSIS_INELIGIBLE" },
  ];
  return <div data-testid="eligibility-breakdown">
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mt-4">
      {funnel.map(f => <div key={f.testid} className="feature-card !p-3">
        <p className="text-xs muted leading-snug">{f.label}</p>
        <p className="text-lg tabular-nums mt-1" data-testid={f.testid}>{numberText(f.value, 0)}</p>
      </div>)}
    </div>
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mt-2">
      {breakdown.map(f => <div key={f.key} className="feature-card !p-2">
        <p className="text-xs muted">{f.label}</p>
        <p className="text-sm tabular-nums" data-testid={`excluded-${f.key.toLowerCase().replace(/_/g, "-")}`}>{numberText(summary.excluded_by_reason[f.key] ?? 0, 0)}</p>
      </div>)}
    </div>
  </div>;
}

/** 列详情：definition/method/version/gates/provenance/validation（来自 feature_meta + tof_provenance）。 */
export function FeatureColumnDrawer({ feature, meta, tof, onClose }: {
  feature: string | null;
  meta?: Record<string, FeatureMetaEntry>;
  tof?: FeatureLabelPreviewResponse["tof_provenance"];
  onClose: () => void;
}) {
  return <Dialog open={!!feature} onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>列详情 / Column details · {feature}</DialogTitle>
        <DialogDescription>definition · method · version · gates · provenance · validation — 全部来自后端，前端零计算。</DialogDescription>
      </DialogHeader>
      {feature && meta && (() => { const m = meta[feature]; if (!m) return null; return <dl className="grid grid-cols-[180px_1fr] gap-x-4 gap-y-1.5 text-sm" data-testid="feature-column-details">
        <dt className="muted">名称 / Name</dt><dd>{m.label_en} / {m.label_zh}</dd>
        <dt className="muted">单位 / Units</dt><dd className="font-mono text-xs">{m.units}</dd>
        <dt className="muted">来源 / Source</dt><dd className="text-xs">{m.source === "physical" ? "物理模块（规范方法）" : m.source === "catalogue" ? "MATLAB 特征目录" : "raw 别名（gates engine）"}</dd>
        <dt className="muted">Definition status</dt><dd className="text-xs font-mono">{m.definition_status}</dd>
        <dt className="muted">Validation / Parity</dt><dd className="text-xs font-mono">{m.parity_status}</dd>
        {m.canonical_note && <><dt className="muted">TOF 说明</dt><dd className="text-xs">{m.canonical_note}</dd></>}
        {feature === "TOF_XCORR" && tof && <><dt className="muted">规范 TOF 方法</dt><dd className="text-xs font-mono">{tof.canonical_method} · v{tof.tof_definition_version}</dd>
          <dt className="muted">fs provenance</dt><dd className="text-xs font-mono">{tof.fs_hz != null ? `${numberText(tof.fs_hz / 1e6, 0)} MHz` : "—"}{tof.fs_verified ? " · 已验证" : " · 未验证"}（{tof.fs_parameter_set_id ?? "—"}）</dd>
          <dt className="muted">GateCalibrationRecord</dt><dd className="text-xs font-mono">{tof.gate_calibration_id}（{tof.gate_calibration_source} v{tof.gate_calibration_version}）</dd>
          <dt className="muted">双闸门</dt><dd className="text-xs font-mono">{tof.surface_gate_id} / {tof.bottom_gate_id}</dd></>}
      </dl>; })()}
    </DialogContent>
  </Dialog>;
}

export function FeatureLabelRowDrawer({ row, targetId, features, onClose }: {
  row: FeatureLabelPreviewRow | null; targetId: string; features: string[]; onClose: () => void;
}) {
  return <Dialog open={!!row} onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>行级来源链 / Row provenance</DialogTitle>
        <DialogDescription>frame → MeasurementEvent → electrical locator → sync → Target → feature producer</DialogDescription>
      </DialogHeader>
      {row && <dl className="grid grid-cols-[180px_1fr] gap-x-4 gap-y-1.5 text-sm" data-testid="feature-label-row-provenance">
        <dt className="muted">Ultrasound frame / 超声帧</dt><dd className="tabular-nums">{row.frame_index_raw ?? "—"}</dd>
        <dt className="muted">MeasurementEvent</dt><dd className="text-xs"><code>{row.measurement_event_id}</code></dd>
        <dt className="muted">Electrical locator</dt><dd className="text-xs font-mono">{row.electrical_record_locator ?? "null（ambiguous — 未选择）"}</dd>
        <dt className="muted">Electrical 行/时间戳</dt><dd className="text-xs font-mono">{row.electrical_row_index ?? "—"} · {row.electrical_timestamp ?? "—"}</dd>
        <dt className="muted">Electrical asset</dt><dd className="text-xs">{row.electrical_asset_id ?? "null"}</dd>
        <dt className="muted">Match status</dt><dd className="text-xs font-mono">{row.match_status ?? "—"}</dd>
        <dt className="muted">Sync error / 同步误差</dt><dd className="tabular-nums text-xs">{numberText(row.sync_error_s, 4)} s（provisional timebase）</dd>
        <dt className="muted">Target / 目标值</dt>
        <dd>{TARGET_LABELS[targetId] ?? targetId} = {row.y_redacted
          ? <span className="inline-flex gap-1 items-center" data-testid="row-y-redacted"><EyeOff size={13}/>已封锁（HELD_OUT y 由后端封锁，evaluation 物化后才可见）</span>
          : <span className="tabular-nums">{numberText(row.target, 3)}</span>}</dd>
        {row.split_role && <><dt className="muted">Split role</dt><dd className="text-xs font-mono">{row.split_role} · {row.fold}</dd></>}
        <dt className="muted">Feature producer</dt><dd className="text-xs">{features.map(f => FEATURE_LABELS[f] ?? f).join(" · ")}</dd>
      </dl>}
    </DialogContent>
  </Dialog>;
}

/** BRW-025R-FE-R2 — Feature–Label Table Preview（强化版）。
 *  一行 = 一个 eligible MeasurementEvent（measurement_event_id 精确 join）；
 *  顶部 X/y/rows/grain/excluded/missing；中英列名+units；50 行分页；
 *  列详情 + 行 provenance + ambiguous inspect + HELD_OUT y 后端封锁显示；
 *  PREVIEW_DRAFT ≠ MATERIALIZED_DATASET；stale TOF → Refresh required。
 *  filter/sort/search 仅 view，不改 dataset identity。 */
export function FeatureLabelTablePreview({ batteryId, experimentId, targetId, features, splitId, foldIndex }: {
  batteryId: string; experimentId: string; targetId: string; features: string[];
  splitId?: string; foldIndex?: string;
}) {
  const [openRow, setOpenRow] = useState<FeatureLabelPreviewRow | null>(null);
  const [columnDetail, setColumnDetail] = useState<string | null>(null);
  const [showAmbiguous, setShowAmbiguous] = useState(false);
  const [page, setPage] = useState(0);
  const [stateFilter, setStateFilter] = useState<string>("ALL");
  const [search, setSearch] = useState("");
  const [sortDesc, setSortDesc] = useState<boolean | null>(null);
  const preview = useMutation({
    mutationFn: () => client.postFeatureLabelPreview(batteryId, experimentId, {
      target_id: targetId, features, split_id: splitId || undefined, fold_index: foldIndex || undefined,
      limit: 500,  // 后端单次上限；50 行/页分页在此之上进行（仅 view）
    }),
  });
  function run() { setPage(0); preview.mutate(); }
  const d = preview.data?.data;
  const meta = d?.feature_meta;

  const filteredRows = useMemo(() => {
    if (!d) return [];
    let rows = [...d.rows];
    if (stateFilter !== "ALL") rows = rows.filter(r => r.state === stateFilter);
    if (search.trim()) rows = rows.filter(r => r.measurement_event_id.toLowerCase().includes(search.trim().toLowerCase()));
    if (sortDesc !== null) rows.sort((a, b) => (sortDesc ? b.target! - a.target! : a.target! - b.target!));
    return rows;
  }, [d, stateFilter, search, sortDesc]);

  const pageCount = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const pageRows = filteredRows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return <div data-testid="feature-label-table">
    <div className="flex gap-3 items-center flex-wrap">
      <Button onClick={run} data-testid="preview-table-btn" disabled={!features.length}>
        预览特征-标签表 / Preview Feature–Label Table</Button>
      {features.length === 0 && <span className="text-xs muted">先在 Features 步骤选择特征。</span>}
      {splitId && <Badge variant="outline" data-testid="preview-split-badge">Split 感知 · {foldIndex}</Badge>}
    </div>
    {preview.isPending && <LoadingState />}
    {preview.error && <ErrorState error={preview.error} retry={() => preview.mutate()} />}
    {d && <>
      {/* 顶部 X/y/rows/grain/excluded/missing */}
      <div className="grid md:grid-cols-4 gap-3 mt-4" data-testid="feature-label-summary">
        {[
          { label: "X（特征）", value: `${d.features.length} 列`, testid: "summary-x" },
          { label: "y（目标）", value: TARGET_LABELS[d.target_id] ?? d.target_id, testid: "summary-y" },
          { label: "行数（eligible / excluded）", value: `${numberText(d.summary.eligible_rows, 0)} / ${numberText(d.summary.excluded_rows, 0)}`, testid: "summary-rows" },
          { label: "粒度 / grain", value: "一行 = 一个 eligible MeasurementEvent", testid: "summary-grain" },
          { label: "排除 / Excluded", value: numberText(d.summary.excluded_rows, 0), testid: "summary-excluded" },
          { label: "缺失 / Missing", value: String(d.summary.missing_values), testid: "summary-missing" },
          { label: "状态", value: d.preview_state ?? "PREVIEW_DRAFT", testid: "summary-state" },
          { label: "Spec hash", value: d.spec_hash ?? "—", testid: "summary-spec-hash" },
        ].map(x => <div key={x.label} className="feature-card !p-3" data-testid={x.testid}>
          <p className="text-xs muted">{x.label}</p>
          <p className="text-sm mt-1 truncate" title={String(x.value)}>{x.value}</p>
        </div>)}
      </div>

      {/* stale TOF dataset banner */}
      {d.materialized_dataset?.refresh_required && <p className="notice !py-2 text-sm mt-3" data-testid="stale-tof-banner">
        <RefreshCw size={14} className="inline mr-1"/>{d.materialized_dataset.stale_note}
        {" "}（materialized {d.materialized_dataset.dataset_id}）
      </p>}

      {/* HELD_OUT 后端封锁摘要 */}
      {d.redaction_summary && <p className="notice !py-2 text-sm mt-3" data-testid="redaction-summary">
        <EyeOff size={14} className="inline mr-1"/>ML-safe Review（fold {d.redaction_summary.fold}）：TRAIN {numberText(d.redaction_summary.train_rows, 0)} 行 y 可见 ·
        HELD_OUT {numberText(d.redaction_summary.held_out_rows, 0)} 行 y 已由后端封锁（evaluation 物化后才可见）。
      </p>}

      <EligibilityBreakdown summary={d.summary} />

      {/* view-only controls */}
      <div className="flex gap-2 items-center mt-4 flex-wrap">
        <label className="text-xs muted">状态过滤
          <select data-testid="fl-state-filter" className="ml-1" value={stateFilter} onChange={e => { setStateFilter(e.target.value); setPage(0); }}>
            <option value="ALL">全部</option><option value="charge">充电</option>
            <option value="discharge">放电</option><option value="rest">静置</option>
          </select>
        </label>
        <label className="text-xs muted">搜索
          <Input data-testid="fl-search" className="!w-56 ml-1" placeholder="measurement_event_id" value={search}
            onChange={e => { setSearch(e.target.value); setPage(0); }}/>
        </label>
        <label className="text-xs muted">y 排序
          <select data-testid="fl-sort" className="ml-1" value={sortDesc === null ? "NONE" : sortDesc ? "DESC" : "ASC"}
            onChange={e => { setSortDesc(e.target.value === "NONE" ? null : e.target.value === "DESC"); setPage(0); }}>
            <option value="NONE">默认</option><option value="DESC">降序</option><option value="ASC">升序</option>
          </select>
        </label>
        <span className="text-xs muted">（filter/sort/search 仅 view，不改 dataset identity）</span>
      </div>

      <div className="mt-3 overflow-x-auto">
        <Table>
          <TableHeader><TableRow>
            <TableHead>Event</TableHead>
            {d.features.map(f => <TableHead key={f}>
              <button className="inline-flex gap-1 items-center hover:underline" data-testid={`col-header-${f}`}
                onClick={() => setColumnDetail(f)} title="查看列详情">
                {meta?.[f] ? `${meta[f].label_zh} / ${meta[f].label_en}` : FEATURE_LABELS[f] ?? f}
                {meta?.[f] && <span className="muted font-normal">[{meta[f].units}]</span>}
                <Info size={11} className="muted"/>
              </button>
            </TableHead>)}
            <TableHead>{TARGET_LABELS[d.target_id] ?? d.target_id}</TableHead>
            <TableHead>状态</TableHead>
            {splitId && <TableHead>Split</TableHead>}
          </TableRow></TableHeader>
          <TableBody>
            {pageRows.map(r => <TableRow key={r.measurement_event_id} data-testid={`fl-row-${r.measurement_event_id}`}
              className="cursor-pointer" onClick={() => setOpenRow(r)}>
              <TableCell className="text-xs">{r.frame_index_raw}</TableCell>
              {d.features.map(f => <TableCell key={f} className="tabular-nums">{numberText(r.values[f], 2)}</TableCell>)}
              <TableCell className="tabular-nums font-medium">
                {r.y_redacted
                  ? <span className="inline-flex gap-1 items-center text-xs muted" data-testid="cell-y-redacted"><EyeOff size={11}/>已封锁</span>
                  : numberText(r.target, 2)}
              </TableCell>
              <TableCell className="text-xs">{STATE_ZH[r.state] ?? r.state}</TableCell>
              {splitId && <TableCell className="text-xs">{r.split_role === "HELD_OUT"
                ? <Badge variant="outline" className="text-[10px]">HELD_OUT</Badge>
                : <Badge variant="secondary" className="text-[10px]">TRAIN</Badge>}</TableCell>}
            </TableRow>)}
          </TableBody>
        </Table>
        <div className="flex gap-3 items-center mt-2 text-xs muted" data-testid="fl-pagination">
          <span>{filteredRows.length} 行（后端返回上限 500；第 {page + 1}/{pageCount} 页 · 50 行/页）</span>
          <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}>上一页</Button>
          <Button variant="outline" size="sm" disabled={page >= pageCount - 1} onClick={() => setPage(p => p + 1)}>下一页</Button>
          <span>一行 = 一个 eligible MeasurementEvent · 点击行查看 provenance。</span>
        </div>
      </div>

      {/* ambiguous rows：可 inspect，但 identity/target null */}
      {d.ambiguous_rows && d.ambiguous_rows.length > 0 && <div className="mt-4">
        <Button variant="ghost" size="sm" data-testid="toggle-ambiguous" onClick={() => setShowAmbiguous(v => !v)}>
          <Eye size={13} className="mr-1"/>{showAmbiguous ? "隐藏" : "查看"}歧义同步行（{d.ambiguous_rows.length}）— electrical identity null · target 不可用 · 不自动 nearest
        </Button>
        {showAmbiguous && <table className="w-full text-xs mt-2" data-testid="ambiguous-rows-table">
          <thead><tr><th className="text-left muted py-1">Event</th><th className="text-left muted">帧</th><th className="text-left muted">状态</th>
            <th className="text-left muted">Electrical identity</th><th className="text-left muted">y</th><th className="text-right muted">候选数</th></tr></thead>
          <tbody>{d.ambiguous_rows.map(a => <tr key={a.measurement_event_id} data-testid={`ambiguous-row-${a.measurement_event_id}`}>
            <td className="font-mono">{a.measurement_event_id.split("::").slice(-2).join("::")}</td>
            <td>{a.frame_index_raw}</td><td>{STATE_ZH[a.state] ?? a.state}</td>
            <td className="muted">null（未选择）</td><td className="muted">不可用</td>
            <td className="text-right tabular-nums">{numberText(a.candidate_count, 0)}</td>
          </tr>)}</tbody>
        </table>}
      </div>}

      <FeatureLabelRowDrawer row={openRow} targetId={d.target_id} features={d.features} onClose={() => setOpenRow(null)} />
      <FeatureColumnDrawer feature={columnDetail} meta={meta} tof={d.tof_provenance} onClose={() => setColumnDetail(null)} />
    </>}
  </div>;
}
