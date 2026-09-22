import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { getCoreRowModel, getSortedRowModel, useReactTable, flexRender, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { client, type ResultRecord } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from "../../components/ui/table";
import { PageHeader, LoadingState, ErrorState, EmptyState, ScopeNote } from "../../components/workbench/shared";
import { SelectedFeaturesPanel } from "../../components/workbench/SelectedFeaturesPanel";
import { displayName, modelComparison, numberText } from "../../lib/presentation";
import { StaleBanner } from "./WorkbenchShell";
import { useWorkflowContext } from "../../hooks/useWorkflowContext";

function ComparisonTable({rows}:{rows:ResultRecord[]}) {
  const [sorting,setSorting]=useState<SortingState>([]);
  const columns=useMemo<ColumnDef<ResultRecord>[]>(()=>[
    {accessorKey:"strategy",header:"模型",cell:ctx=><span className="font-medium">{displayName(String(ctx.getValue()))}{ctx.getValue()==="DUMMY_MEAN" && <Badge variant="secondary" className="ml-3">参考基线</Badge>}</span>},
    {accessorKey:"value",header:"宏观 MAE（%）",cell:ctx=><span className="tabular-nums">{numberText(ctx.getValue())}</span>},
    {accessorKey:"scientific_status",header:"范围",cell:()=>"有限评估"},
  ],[]);
  const table=useReactTable({data:rows,columns,state:{sorting},onSortingChange:setSorting,getCoreRowModel:getCoreRowModel(),getSortedRowModel:getSortedRowModel()});
  return <Table><TableHeader>{table.getHeaderGroups().map(g=><TableRow key={g.id}>{g.headers.map(h=><TableHead key={h.id}><button onClick={h.column.getToggleSortingHandler()} aria-label={`按 ${h.column.id} 排序`}>{flexRender(h.column.columnDef.header,h.getContext())}</button></TableHead>)}</TableRow>)}</TableHeader><TableBody>{table.getRowModel().rows.map(r=><TableRow key={r.id} className={r.original.strategy==="DUMMY_MEAN"?"bg-[#f1f5f4]":""}>{r.getVisibleCells().map(c=><TableCell key={c.id}>{flexRender(c.column.columnDef.cell,c.getContext())}</TableCell>)}</TableRow>)}</TableBody></Table>;
}
/**
 * Dataset → modeling handoff (official orchestrator path only):
 * shows the prerequisite chain, creates the grouped split when missing,
 * offers a read-only dry-run plan and a FULL_PRE_MODEL run start. Run
 * progress and user actions (CONFIRM_FEATURE_SELECTION etc.) are handled
 * on the Runs page — this panel never trains or rebuilds implicitly.
 */
function ModelingLauncher({ batteryId, experimentId, wf }: { batteryId: string; experimentId: string; wf: ReturnType<typeof useWorkflowContext>["data"] }) {
  const qc = useQueryClient();
  const splitsQ = useQuery({ queryKey: ["splits", batteryId, experimentId], queryFn: () => client.listSplits(batteryId, experimentId) });
  const runsQ = useQuery({ queryKey: ["runs", 5], queryFn: () => client.listRuns(5) });
  const steps = wf?.steps ?? {};
  const datasetId = (steps.DATASET?.committed as { dataset_id?: string } | undefined)?.dataset_id
    ?? (steps.SPLIT?.committed as { dataset_id?: string } | undefined)?.dataset_id ?? null;
  const hasSplit = !!(steps.SPLIT?.committed as { split_id?: string } | undefined)?.split_id
    || (splitsQ.data?.data.splits ?? []).length > 0;
  const waitingRun = (runsQ.data?.data.runs ?? []).find(r => r.status === "WAITING_FOR_USER" && r.experiment_id === experimentId);
  const createSplit = useMutation({
    mutationFn: () => client.createSplit({ battery_id: batteryId, experiment_id: experimentId, dataset_id: datasetId! }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["splits", batteryId, experimentId] }); },
  });
  const dryRun = useMutation({ mutationFn: () => client.dryRun({ profile: "FULL_PRE_MODEL", battery_id: batteryId, experiment_id: experimentId }) });
  const startRun = useMutation({
    mutationFn: () => client.startRun({ profile: "FULL_PRE_MODEL", battery_id: batteryId, experiment_id: experimentId }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["runs", 5] }); },
  });
  const planned = (dryRun.data?.data as { nodes?: { node_id: string; state: string }[] } | undefined)?.nodes ?? [];
  return <section className="panel !p-5 mt-6" data-testid="modeling-launcher">
    <h3 className="text-base font-medium">建模流程接入 / Modeling handoff</h3>
    <p className="text-sm muted mt-1">链路：数据集 → 分组划分 → 训练运行（官方编排器 FULL_PRE_MODEL）。特征锁定确认在运行页以“用户动作”完成，系统不会自动重建或自动训练。</p>
    <p className="text-sm mt-3" data-testid="launcher-chain">
      数据集: <strong>{datasetId ? "已就绪" : "未构建"}</strong> · 分组划分: <strong>{hasSplit ? "已就绪" : "缺失"}</strong>
    </p>
    {!datasetId && <p className="text-sm mt-2">先到 <Link className="underline" to={`/experiments/${batteryId}/${experimentId}/analysis?step=dataset`}>特征分析 → 数据集</Link> 构建数据集。</p>}
    {datasetId && !hasSplit && <p className="mt-2"><Button variant="outline" size="sm" data-testid="launcher-create-split" disabled={createSplit.isPending}
      onClick={() => createSplit.mutate()}>{createSplit.isPending ? "创建中…" : "创建分组划分 / Create grouped split"}</Button></p>}
    {waitingRun && <p className="notice text-sm mt-2" role="status" data-testid="launcher-waiting-run">
      有一个运行正在等待你的确认（特征选择/参数）：<Link className="underline" to="/runs">前往运行页处理</Link></p>}
    <div className="flex gap-3 mt-3 items-center flex-wrap">
      <Button variant="outline" size="sm" data-testid="launcher-dry-run" disabled={!datasetId || !hasSplit || dryRun.isPending}
        onClick={() => dryRun.mutate()}>{dryRun.isPending ? "计划中…" : "查看运行计划（只读 dry-run）"}</Button>
      <Button size="sm" data-testid="launcher-start-run" disabled={!datasetId || !hasSplit || !!waitingRun || startRun.isPending}
        onClick={() => startRun.mutate()}>{startRun.isPending ? "启动中…" : "启动建模运行 / Start run"}</Button>
      {startRun.isSuccess && <span className="text-sm">已启动：<code>{String((startRun.data as { data?: { run_id?: string } })?.data?.run_id ?? "").slice(0, 28)}</code> · <Link className="underline" to="/runs">运行页跟踪与确认</Link></span>}
      {startRun.error && <span className="text-sm text-[#9b782e]" data-testid="launcher-start-error">启动失败：{(startRun.error as Error).message?.slice(0, 120)}</span>}
    </div>
    {planned.length > 0 && <ul className="text-xs muted mt-3 grid grid-cols-2 gap-x-6 gap-y-1" data-testid="launcher-plan">
      {planned.map(n => <li key={n.node_id}>{n.node_id} — {n.state}</li>)}
    </ul>}
  </section>;
}

export function ModelsWorkbench() {
  const {batteryId="",experimentId=""}=useParams();
  const wf = useWorkflowContext(batteryId, experimentId);
  const results=useQuery({queryKey:["results",batteryId,experimentId],queryFn:()=>client.getResults(batteryId,experimentId)});
  if(results.isLoading)return <LoadingState/>;if(results.error)return <ErrorState error={results.error} retry={()=>void results.refetch()}/>;
  const rows=results.data?.data??[];const {macro,dummy,beats}=modelComparison(rows);
  const datasetIds=[...new Set(rows.map(r=>r.dataset_id).filter((d): d is string => !!d))];
  return <><PageHeader eyebrow="先看证据，再谈性能" title="SOC 建模" description="有没有模型跑赢简单基线？" actions={<Button variant="outline" asChild><Link to={`/experiments/${batteryId}/${experimentId}/report`}>Open report<ArrowRight/></Link></Button>}/>
    {wf.data && <StaleBanner freshness={wf.data.artifact_freshness} stepKey="MODELS" />}
    <ModelingLauncher batteryId={batteryId} experimentId={experimentId} wf={wf.data} />
    {!macro.length ? <EmptyState title="还没有模型评估" to={`/experiments/${batteryId}/${experimentId}/analysis`}>请先构建数据集和分组划分。特征选择请保留在训练组内。</EmptyState> : <>
      <Badge variant="secondary">评估完成 · 有限范围</Badge><div className="finding"><h2>{beats===false?"当前没有任何模型跑赢 Dummy 基准。":beats===true?"有模型在本次评估中跑赢了 Dummy。":"暂无可比的 Dummy 基线。"}</h2><p className="muted mt-4 max-w-2xl">{beats===false?"当前特征尚未展现出预测优势。这是科学结论，不是处理故障。":"该对比不能证明跨电池泛化或生产可用性。"}</p></div>
      {dummy && <p className="mb-7 text-sm"><span className="muted">Dummy 均值 · 宏观 MAE</span><strong className="text-2xl ml-4 tabular-nums">{numberText(dummy.value)}<span className="text-sm muted ml-1">%</span></strong></p>}
      <section className="panel !p-0 overflow-hidden"><div className="p-5 border-b"><h3>Model comparison</h3><p className="text-xs muted mt-1">Lower MAE is better. Values are reported by the scientific service.</p></div><ComparisonTable rows={macro}/></section>
      <SelectedFeaturesPanel datasetId={datasetIds[0]} />
      <details className="mt-5"><summary>Advanced evaluation details</summary><Table><TableHeader><TableRow><TableHead>模型</TableHead><TableHead>指标</TableHead><TableHead>折</TableHead><TableHead>数值</TableHead><TableHead>证据</TableHead></TableRow></TableHeader><TableBody>{rows.filter(r=>r.result_type==="MODEL_METRIC").map(r=><TableRow key={r.result_id}><TableCell>{displayName(r.strategy??"")}</TableCell><TableCell>{r.name}</TableCell><TableCell>{r.fold_index??"—"}</TableCell><TableCell>{numberText(r.value)} {r.units}</TableCell><TableCell>{displayName(r.evidence_type)}</TableCell></TableRow>)}</TableBody></Table><p className="muted text-sm mt-3">OOB 与方向性指标仅在后端提供时显示。此处不计算池化行指标。</p></details>
    </>}<ScopeNote/></>;
}
