import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
export function ModelsWorkbench() {
  const {batteryId="",experimentId=""}=useParams();
  const results=useQuery({queryKey:["results",batteryId,experimentId],queryFn:()=>client.getResults(batteryId,experimentId)});
  if(results.isLoading)return <LoadingState/>;if(results.error)return <ErrorState error={results.error} retry={()=>void results.refetch()}/>;
  const rows=results.data?.data??[];const {macro,dummy,beats}=modelComparison(rows);
  const datasetIds=[...new Set(rows.map(r=>r.dataset_id).filter((d): d is string => !!d))];
  return <><PageHeader eyebrow="先看证据，再谈性能" title="SOC 建模" description="有没有模型跑赢简单基线？" actions={<Button variant="outline" asChild><Link to={`/experiments/${batteryId}/${experimentId}/report`}>Open report<ArrowRight/></Link></Button>}/>
    {!macro.length ? <EmptyState title="还没有模型评估" to={`/experiments/${batteryId}/${experimentId}/analysis`}>请先构建数据集和分组划分。特征选择请保留在训练组内。</EmptyState> : <>
      <Badge variant="secondary">评估完成 · 有限范围</Badge><div className="finding"><h2>{beats===false?"当前没有任何模型跑赢 Dummy 基准。":beats===true?"有模型在本次评估中跑赢了 Dummy。":"暂无可比的 Dummy 基线。"}</h2><p className="muted mt-4 max-w-2xl">{beats===false?"当前特征尚未展现出预测优势。这是科学结论，不是处理故障。":"该对比不能证明跨电池泛化或生产可用性。"}</p></div>
      {dummy && <p className="mb-7 text-sm"><span className="muted">Dummy 均值 · 宏观 MAE</span><strong className="text-2xl ml-4 tabular-nums">{numberText(dummy.value)}<span className="text-sm muted ml-1">%</span></strong></p>}
      <section className="panel !p-0 overflow-hidden"><div className="p-5 border-b"><h3>Model comparison</h3><p className="text-xs muted mt-1">Lower MAE is better. Values are reported by the scientific service.</p></div><ComparisonTable rows={macro}/></section>
      <SelectedFeaturesPanel datasetId={datasetIds[0]} />
      <details className="mt-5"><summary>Advanced evaluation details</summary><Table><TableHeader><TableRow><TableHead>模型</TableHead><TableHead>指标</TableHead><TableHead>折</TableHead><TableHead>数值</TableHead><TableHead>证据</TableHead></TableRow></TableHeader><TableBody>{rows.filter(r=>r.result_type==="MODEL_METRIC").map(r=><TableRow key={r.result_id}><TableCell>{displayName(r.strategy??"")}</TableCell><TableCell>{r.name}</TableCell><TableCell>{r.fold_index??"—"}</TableCell><TableCell>{numberText(r.value)} {r.units}</TableCell><TableCell>{displayName(r.evidence_type)}</TableCell></TableRow>)}</TableBody></Table><p className="muted text-sm mt-3">OOB 与方向性指标仅在后端提供时显示。此处不计算池化行指标。</p></details>
    </>}<ScopeNote/></>;
}
