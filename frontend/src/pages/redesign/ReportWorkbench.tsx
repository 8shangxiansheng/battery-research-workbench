import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, Download, FileText } from "lucide-react";
import { client } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../../components/workbench/shared";
import { displayName, modelComparison } from "../../lib/presentation";

export function ReportWorkbench() {
  const {batteryId="",experimentId=""}=useParams();const qc=useQueryClient(); const [confirm,setConfirm]=useState(false); const [exportError,setExportError]=useState(false);
  const reports=useQuery({queryKey:["reports",batteryId,experimentId],queryFn:()=>client.listReports(batteryId,experimentId)});
  const limitations=useQuery({queryKey:["limitations",batteryId,experimentId],queryFn:()=>client.getLimitations(batteryId,experimentId)});
  const results=useQuery({queryKey:["results",batteryId,experimentId],queryFn:()=>client.getResults(batteryId,experimentId)});
  const create=useMutation({mutationFn:()=>client.createReport({battery_id:batteryId,experiment_id:experimentId}),onSuccess:()=>{setConfirm(false);void qc.invalidateQueries({queryKey:["reports",batteryId,experimentId]});}});
  const list=reports.data?.data??[]; const dated=list.filter(r=>typeof r.generated_at==="string").sort((a,b)=>String(b.generated_at).localeCompare(String(a.generated_at)));
  const report=dated[0]??list[0];const comparison=modelComparison(results.data?.data??[]);
  async function exportReport(){try {const r=await client.getReport(String(report?.report_id));const url=URL.createObjectURL(new Blob([JSON.stringify(r.data,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download="scientific-report.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch{setExportError(true);}}
  if(reports.isLoading)return <LoadingState/>;if(reports.error)return <ErrorState error={reports.error} retry={()=>void reports.refetch()}/>;
  return <><PageHeader eyebrow="A traceable research record" title="Report" description="Findings, limitations, and the evidence behind them." actions={<Button variant="outline" onClick={()=>{setConfirm(true);create.reset();}}><FileText/>Generate report</Button>}/>
    {!report ? <EmptyState title="No report yet" to={`/experiments/${batteryId}/${experimentId}/models`} action="Review model results">Review available results, then generate a report from existing scientific artifacts.</EmptyState> : <article className="panel !p-8"><div className="flex justify-between gap-4 items-start"><div><p className="eyebrow">{dated.length?"Latest report":"Available report"}</p><h2 className="text-2xl">Experiment research summary</h2><p className="muted text-sm mt-2">{batteryId} / {experimentId} · {report.generated_at ? String(report.generated_at) : "Generation time not provided"}</p></div><Button variant="outline" onClick={()=>void exportReport()}><Download/>Export JSON</Button></div>
      <div className="mt-7 flex gap-2"><Badge variant="secondary">Reference SOC</Badge><Badge variant="outline">Limited evaluation</Badge></div>
      <div className="finding"><h2>{comparison.beats===false?"Predictive advantage has not been demonstrated.":comparison.beats===true?"A model surpassed the baseline within this study.":"Review the available evidence before drawing a conclusion."}</h2><p className="muted mt-3">Current experiment results, shown alongside the report. They are not asserted to be a frozen report snapshot.</p></div>
      <h3 className="mt-7 mb-3">Limitations to keep with this result</h3>{limitations.error?<ErrorState error={limitations.error} retry={()=>void limitations.refetch()}/>:<ul className="space-y-3 text-sm muted list-disc pl-5">{limitations.data?.data.limitations.map(l=><li key={l.code}>{l.description}</li>)}</ul>}
      <details className="mt-7 border-t pt-3"><summary>Evidence & reproducibility</summary><p className="muted text-sm">Evidence classes and availability remain as reported by the scientific service.</p><Button variant="link" asChild className="px-0"><Link to={`/experiments/${batteryId}/${experimentId}/advanced/evidence`}>Inspect evidence<ArrowRight/></Link></Button><p className="text-xs muted">Report identity: <code>{String(report.report_id)}</code></p>{Array.isArray(report.limitations)&&<p className="text-xs muted mt-2">Report limitations: {report.limitations.map(l=>displayName(String(l))).join(" · ")}</p>}</details>
    </article>}{exportError&&<p role="alert" className="notice mt-4">Export failed. Please retry.</p>}
    <Dialog open={confirm} onOpenChange={setConfirm}><DialogContent><DialogHeader><DialogTitle>Generate scientific report</DialogTitle><DialogDescription>Aggregate existing results for {batteryId} / {experimentId}. This request does not refit models. Identical reports may be reused.</DialogDescription></DialogHeader>{create.error&&<p role="alert">Report could not be generated. Retry after checking available artifacts.</p>}<DialogFooter><Button variant="outline" onClick={()=>setConfirm(false)}>Cancel</Button><Button disabled={create.isPending} onClick={()=>create.mutate()}>Generate report</Button></DialogFooter></DialogContent></Dialog>
  </>;
}
