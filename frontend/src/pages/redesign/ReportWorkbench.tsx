import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, Download, FileText } from "lucide-react";
import { client } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../../components/workbench/shared";
import { SelectedFeaturesPanel } from "../../components/workbench/SelectedFeaturesPanel";
import { displayName, modelComparison } from "../../lib/presentation";

export function ReportWorkbench() {
  const {batteryId="",experimentId=""}=useParams();const qc=useQueryClient(); const [confirm,setConfirm]=useState(false); const [exportError,setExportError]=useState(false);
  const reports=useQuery({queryKey:["reports",batteryId,experimentId],queryFn:()=>client.listReports(batteryId,experimentId)});
  const limitations=useQuery({queryKey:["limitations",batteryId,experimentId],queryFn:()=>client.getLimitations(batteryId,experimentId)});
  const results=useQuery({queryKey:["results",batteryId,experimentId],queryFn:()=>client.getResults(batteryId,experimentId)});
  const create=useMutation({mutationFn:()=>client.createReport({battery_id:batteryId,experiment_id:experimentId}),onSuccess:()=>{setConfirm(false);void qc.invalidateQueries({queryKey:["reports",batteryId,experimentId]});}});
  const list=reports.data?.data??[]; const dated=list.filter(r=>typeof r.generated_at==="string").sort((a,b)=>String(b.generated_at).localeCompare(String(a.generated_at)));
  const report=dated[0]??list[0];const comparison=modelComparison(results.data?.data??[]);
  const datasetIds=[...new Set((results.data?.data??[]).map(r=>r.dataset_id).filter((d): d is string => !!d))];
  const corr=useQuery({queryKey:["feature-correlations",batteryId,experimentId,"SWA",400],queryFn:()=>client.getFeatureCorrelations(batteryId,experimentId,"SWA",4000),});
  async function exportReport(){try {const r=await client.getReport(String(report?.report_id));const url=URL.createObjectURL(new Blob([JSON.stringify(r.data,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download="scientific-report.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch{setExportError(true);}}
  if(reports.isLoading)return <LoadingState/>;if(reports.error)return <ErrorState error={reports.error} retry={()=>void reports.refetch()}/>;
  return <><PageHeader eyebrow="可追溯的研究记录" title="科学报告" description="结论、限制，以及它们背后的证据。" actions={<Button variant="outline" onClick={()=>{setConfirm(true);create.reset();}}><FileText/>生成报告</Button>}/>
    {!report ? <EmptyState title="还没有报告" to={`/experiments/${batteryId}/${experimentId}/models`} action="查看模型结果">先查看可用结果，再从既有科学产物生成报告。</EmptyState> : <article className="panel !p-8"><div className="flex justify-between gap-4 items-start"><div><p className="eyebrow">{dated.length?"最新报告":"可用报告"}</p><h2 className="text-2xl">实验研究摘要</h2><p className="muted text-sm mt-2">{batteryId} / {experimentId} · {report.generated_at ? String(report.generated_at) : "未提供生成时间"}</p></div><Button variant="outline" onClick={()=>void exportReport()}><Download/>导出 JSON</Button></div>
      <div className="mt-7 flex gap-2"><Badge variant="secondary">Reference SOC</Badge><Badge variant="outline">Limited evaluation</Badge></div>
      <div className="finding"><h2>{comparison.beats===false?"Predictive advantage has not been demonstrated.":comparison.beats===true?"A model surpassed the baseline within this study.":"Review the available evidence before drawing a conclusion."}</h2><p className="muted mt-3">Current experiment results, shown alongside the report. They are not asserted to be a frozen report snapshot.</p></div>
      <h3 className="mt-7 mb-3">随本结果保留的限制</h3>{limitations.error?<ErrorState error={limitations.error} retry={()=>void limitations.refetch()}/>:<ul className="space-y-3 text-sm muted list-disc pl-5">{limitations.data?.data.limitations.map(l=><li key={l.code}>{l.description}</li>)}</ul>}
      <SelectedFeaturesPanel datasetId={datasetIds[0]} />
      <section className="panel mt-6 !p-5" data-testid="report-feature-summary">
        <h2>Feature workbench summary / 特征工作台摘要</h2>
        <p className="muted text-sm mt-1">闸门标定与特征-状态相关性摘要（后端报告）；内部 artifact ID 不作主要显示。</p>
        {corr.data?.data && <>
          <ul className="mt-3 space-y-2 text-sm list-disc pl-5">
            <li>标定流程：24–40 代表帧确定性选择（PREDECLARED_PROTOCOL_GATE，目标盲选），确认后冻结 GateCalibrationRecord；配置变更需重新标定。</li>
            <li>SWA 与 Reference SOC：Pearson {(() => { const r = corr.data!.data.soc.find(x => x.scope === "overall" && x.method === "pearson"); return r?.coefficient != null ? r.coefficient.toFixed(3) : "—"; })()}（overall）· 分层 charge/discharge/rest 由后端报告。</li>
            <li>温度：{corr.data.data.temperature.status==="TEMPERATURE_UNAVAILABLE"?"本实验无温度通道":corr.data.data.temperature.status}。</li>
            <li>SOH：{corr.data.data.soh.status==="NOT_READY_INSUFFICIENT_SOH_STATES"?"仅 2 个独立状态 — 相关性不适用（limited）":corr.data.data.soh.status} · cycle 级摘要 {corr.data.data.soh_cycle_summary.length} 个循环。</li>
            <li>无 naive p 值：波形帧存在时间自相关。</li>
          </ul>
        </>}
        {corr.isLoading && <LoadingState/>}{corr.error && <ErrorState error={corr.error} retry={()=>void corr.refetch()}/>}
      </section>
      <details className="mt-7 border-t pt-3"><summary>证据与可复现性</summary><p className="muted text-sm">证据类别与可用性以科学服务报告为准。</p><Button variant="link" asChild className="px-0"><Link to={`/experiments/${batteryId}/${experimentId}/advanced/evidence`}>查看证据<ArrowRight/></Link></Button><p className="text-xs muted">报告标识：<code>{String(report.report_id)}</code></p>{Array.isArray(report.limitations)&&<p className="text-xs muted mt-2">报告限制：{report.limitations.map(l=>displayName(String(l))).join(" · ")}</p>}</details>
    </article>}{exportError&&<p role="alert" className="notice mt-4">Export failed. Please retry.</p>}
    <Dialog open={confirm} onOpenChange={setConfirm}><DialogContent><DialogHeader><DialogTitle>Generate scientific report</DialogTitle><DialogDescription>Aggregate existing results for {batteryId} / {experimentId}. This request does not refit models. Identical reports may be reused.</DialogDescription></DialogHeader>{create.error&&<p role="alert">Report could not be generated. Retry after checking available artifacts.</p>}<DialogFooter><Button variant="outline" onClick={()=>setConfirm(false)}>Cancel</Button><Button disabled={create.isPending} onClick={()=>create.mutate()}>Generate report</Button></DialogFooter></DialogContent></Dialog>
  </>;
}
