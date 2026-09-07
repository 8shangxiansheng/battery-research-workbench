import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { client, ApiError } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../../components/workbench/shared";
import { ParameterDialog } from "../../components/workbench/ParameterDialog";
import { displayName } from "../../lib/presentation";
import { RunsPage } from "../RunsPage";
import { DataWorkspacePage } from "../DataWorkspacePage";
import { DatasetSplitPage } from "../DatasetSplitPage";
import { WorkspacePage } from "../WorkspacePage";

function Parameters() {
  const {batteryId="",experimentId=""}=useParams(); const [selected,setSelected]=useState("");
  const params=useQuery({queryKey:["parameters",batteryId,experimentId],queryFn:()=>client.listParameters(batteryId,experimentId),retry:false});
  if(params.isLoading)return <LoadingState/>;
  if(params.error && !(params.error instanceof ApiError && params.error.code==="NOT_FOUND"))return <ErrorState error={params.error} retry={()=>void params.refetch()}/>;
  const sets=params.data?.data??[]; const set=sets.find(s=>s.parameter_set_id===selected)??(sets.length===1?sets[0]:undefined);
  const definitions=[{key:"ultrasound.sampling_rate_hz",label:"采样频率",hint:"绝对时间测量所必需"},{key:"ultrasound.trigger_sample_index",label:"触发 / 时间零点",hint:"仪器定义的参考点"},{key:"ultrasound.system_delay_s",label:"系统延迟",hint:"校准参考"},{key:"electrical.reference_capacity_ah",label:"参考容量",hint:"用于参考 SOC 解释"},{key:"experiment.ultrasound_path_length_m",label:"声程长度",hint:"绝不以电芯厚度代替"}];
  return <section className="panel"><div className="flex justify-between gap-4 items-center mb-6"><div><h2>科学参数</h2><p className="muted text-sm mt-1">记录已知项，未知项保持显式标注。</p></div><ParameterDialog/></div>
    {sets.length>1 && <label className="field mb-5">Parameter version<select value={selected} onChange={e=>setSelected(e.target.value)}><option value="">选择要查看的版本</option>{sets.map((s,i)=><option key={s.parameter_set_id} value={s.parameter_set_id}>版本 {i+1}</option>)}</select><span className="text-xs muted">不假定任何版本为当前生效版本。</span></label>}
    {definitions.map(d=>{const entry=set?.effective[d.key]; const record=entry && typeof entry==="object"?entry as Record<string,unknown>:null;return <div className="data-row" key={d.key}><div className="flex-1"><h3>{d.label}</h3><p className="muted text-sm">{d.hint}</p></div><div className="text-right"><p className="font-medium">{record?.value!==undefined && record.value!==null ? `${String(record.value)} ${String(record.unit??"")}` : "—"}</p><span className="text-xs muted">{record?.verification_status ? displayName(String(record.verification_status)) : "未解析"}</span></div></div>;})}
    <div className="notice mt-6">添加采样频率会记录一个用户提供的值。已验证的时序与下游结果仍由科学服务控制。</div>
    <details className="mt-5"><summary>参数溯源与精确值</summary>{sets.length===0?<p className="muted">暂无参数版本。</p>:sets.map(s=><div key={s.parameter_set_id} className="py-3"><p className="text-xs break-all">{s.parameter_set_id}</p><pre className="text-xs whitespace-pre-wrap break-all mt-2">{JSON.stringify(s.effective,null,2)}</pre></div>)}</details>
    <Button variant="link" asChild className="px-0 mt-3"><Link to={`/experiments/${batteryId}/${experimentId}/advanced/runs`}>处理其他待定的参数请求<ArrowRight/></Link></Button>
  </section>;
}
function Evidence(){const {batteryId="",experimentId=""}=useParams();const q=useQuery({queryKey:["evidence",batteryId,experimentId],queryFn:()=>client.getEvidence(batteryId,experimentId)});if(q.isLoading)return <LoadingState/>;if(q.error)return <ErrorState error={q.error} retry={()=>void q.refetch()}/>;return <section className="panel overflow-auto"><h2 className="mb-5">证据注册表</h2><table><thead><tr><th>证据类型</th><th>来源</th><th>可用性</th></tr></thead><tbody>{q.data?.data.evidence.map((e,i)=><tr key={i}><td><Badge variant="secondary">{displayName(e.evidence_type)}</Badge></td><td><details><summary>来源 {i+1}</summary><code className="text-xs">{e.evidence_ref}</code><p className="text-xs break-all">{e.artifact_id}</p></details></td><td>{displayName(e.artifact_availability)}</td></tr>)}</tbody></table></section>;}
function Lineage(){const {batteryId="",experimentId=""}=useParams();const q=useQuery({queryKey:["lineage",batteryId,experimentId],queryFn:()=>client.getLineage(batteryId,experimentId)});if(q.isLoading)return <LoadingState/>;if(q.error)return <ErrorState error={q.error} retry={()=>void q.refetch()}/>;return <section className="panel"><h2>研究血缘</h2><p className="muted mt-2 mb-6">来自科学服务的阶段列表。展开某阶段可查看其精确标识。</p><ol className="space-y-3">{q.data?.data.lineage_chain.map((n,i)=><li key={`${n.artifact_type}-${i}`} className="border-l-2 border-primary pl-5"><details><summary>{displayName(n.artifact_type)} <Badge variant="outline" className="ml-3">{displayName(n.status)}</Badge></summary><code className="text-xs">{n.artifact_id??"无可用产物"}</code></details></li>)}</ol></section>;}
export function AdvancedPage(){const {batteryId="",experimentId="",section="parameters"}=useParams();const tabs=["parameters","evidence","lineage","artifacts","runs","data","dataset-split"];return <><PageHeader eyebrow="需要时才展开的细节" title="高级" description="参数、溯源与可复现性工具。"/><nav aria-label="Advanced navigation" className="flex gap-2 flex-wrap mb-7">{tabs.map(t=><Button key={t} variant={section===t?"secondary":"ghost"} asChild><Link to={`/experiments/${batteryId}/${experimentId}/advanced/${t}`}>{t==="dataset-split"?"数据集与划分":t==="parameters"?"参数":t==="evidence"?"证据":t==="lineage"?"血缘":t==="artifacts"?"产物":t==="runs"?"运行":t==="data"?"数据":t[0]!.toUpperCase()+t.slice(1)}</Link></Button>)}</nav>{section==="parameters"?<Parameters/>:section==="evidence"?<Evidence/>:section==="lineage"?<Lineage/>:section==="runs"?<div className="legacy-view"><RunsPage/></div>:section==="data"?<div className="legacy-view"><DataWorkspacePage/></div>:section==="dataset-split"?<div className="legacy-view"><DatasetSplitPage/></div>:section==="artifacts"||section==="workspace"?<div className="legacy-view"><WorkspacePage/></div>:<EmptyState title="视图不可用">请从上方选择一个高级分区。</EmptyState>}</>;}
