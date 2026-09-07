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
import { displayName, modelComparison, numberText } from "../../lib/presentation";

function ComparisonTable({rows}:{rows:ResultRecord[]}) {
  const [sorting,setSorting]=useState<SortingState>([]);
  const columns=useMemo<ColumnDef<ResultRecord>[]>(()=>[
    {accessorKey:"strategy",header:"Model",cell:ctx=><span className="font-medium">{displayName(String(ctx.getValue()))}{ctx.getValue()==="DUMMY_MEAN" && <Badge variant="secondary" className="ml-3">Reference baseline</Badge>}</span>},
    {accessorKey:"value",header:"Macro MAE (%)",cell:ctx=><span className="tabular-nums">{numberText(ctx.getValue())}</span>},
    {accessorKey:"scientific_status",header:"Scope",cell:()=>"Limited evaluation"},
  ],[]);
  const table=useReactTable({data:rows,columns,state:{sorting},onSortingChange:setSorting,getCoreRowModel:getCoreRowModel(),getSortedRowModel:getSortedRowModel()});
  return <Table><TableHeader>{table.getHeaderGroups().map(g=><TableRow key={g.id}>{g.headers.map(h=><TableHead key={h.id}><button onClick={h.column.getToggleSortingHandler()} aria-label={`Sort by ${h.column.id}`}>{flexRender(h.column.columnDef.header,h.getContext())}</button></TableHead>)}</TableRow>)}</TableHeader><TableBody>{table.getRowModel().rows.map(r=><TableRow key={r.id} className={r.original.strategy==="DUMMY_MEAN"?"bg-[#f1f5f4]":""}>{r.getVisibleCells().map(c=><TableCell key={c.id}>{flexRender(c.column.columnDef.cell,c.getContext())}</TableCell>)}</TableRow>)}</TableBody></Table>;
}
export function ModelsWorkbench() {
  const {batteryId="",experimentId=""}=useParams();
  const results=useQuery({queryKey:["results",batteryId,experimentId],queryFn:()=>client.getResults(batteryId,experimentId)});
  if(results.isLoading)return <LoadingState/>;if(results.error)return <ErrorState error={results.error} retry={()=>void results.refetch()}/>;
  const rows=results.data?.data??[];const {macro,dummy,beats}=modelComparison(rows);
  return <><PageHeader eyebrow="Evidence before performance claims" title="Models" description="Did any model beat a simple baseline?" actions={<Button variant="outline" asChild><Link to={`/experiments/${batteryId}/${experimentId}/report`}>Open report<ArrowRight/></Link></Button>}/>
    {!macro.length ? <EmptyState title="No model evaluation yet" to={`/experiments/${batteryId}/${experimentId}/analysis`}>Build a dataset and a grouped split first. Keep feature selection inside the training groups.</EmptyState> : <>
      <Badge variant="secondary">Evaluation complete · Limited scope</Badge><div className="finding"><h2>{beats===false?"No evaluated model outperformed Dummy Mean.":beats===true?"A model outperformed Dummy in this evaluation.":"A comparable Dummy baseline is not available."}</h2><p className="muted mt-4 max-w-2xl">{beats===false?"The current features have not demonstrated a predictive advantage. This is a scientific result, not a processing failure.":"This comparison does not demonstrate cross-battery generalization or production readiness."}</p></div>
      {dummy && <p className="mb-7 text-sm"><span className="muted">Dummy Mean · Macro MAE</span><strong className="text-2xl ml-4 tabular-nums">{numberText(dummy.value)}<span className="text-sm muted ml-1">%</span></strong></p>}
      <section className="panel !p-0 overflow-hidden"><div className="p-5 border-b"><h3>Model comparison</h3><p className="text-xs muted mt-1">Lower MAE is better. Values are reported by the scientific service.</p></div><ComparisonTable rows={macro}/></section>
      <details className="mt-5"><summary>Advanced evaluation details</summary><Table><TableHeader><TableRow><TableHead>Model</TableHead><TableHead>Metric</TableHead><TableHead>Fold</TableHead><TableHead>Value</TableHead><TableHead>Evidence</TableHead></TableRow></TableHeader><TableBody>{rows.filter(r=>r.result_type==="MODEL_METRIC").map(r=><TableRow key={r.result_id}><TableCell>{displayName(r.strategy??"")}</TableCell><TableCell>{r.name}</TableCell><TableCell>{r.fold_index??"—"}</TableCell><TableCell>{numberText(r.value)} {r.units}</TableCell><TableCell>{displayName(r.evidence_type)}</TableCell></TableRow>)}</TableBody></Table><p className="muted text-sm mt-3">OOB and direction-specific metrics are only available when exposed by the API. No pooled-row metrics are calculated here.</p></details>
    </>}<ScopeNote/></>;
}
