import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, Waves, Battery, Link2, CheckCircle2 } from "lucide-react";
import { client } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { PageHeader, LoadingState, ErrorState, ScopeNote, ScientificStatus } from "../../components/workbench/shared";
import { modelComparison, numberText } from "../../lib/presentation";
import { ParameterDialog } from "../../components/workbench/ParameterDialog";

export function OverviewPage() {
  const { batteryId = "", experimentId = "" } = useParams(); const base = `/experiments/${batteryId}/${experimentId}`;
  const summary = useQuery({queryKey:["workspace-summary",batteryId,experimentId], queryFn:()=>client.getWorkspaceSummary(batteryId,experimentId)});
  const quality = useQuery({queryKey:["data-quality",batteryId,experimentId], queryFn:()=>client.getDataQuality(batteryId,experimentId)});
  const status = useQuery({queryKey:["status",batteryId,experimentId], queryFn:()=>client.getStatus(batteryId,experimentId)});
  const results = useQuery({queryKey:["results",batteryId,experimentId], queryFn:()=>client.getResults(batteryId,experimentId)});
  if(summary.isLoading) return <LoadingState/>;
  if(summary.error) return <ErrorState error={summary.error} retry={()=>void summary.refetch()}/>;
  const ws=summary.data?.data; const q=quality.data?.data; const comparison=modelComparison(results.data?.data??[]);
  return <><PageHeader eyebrow="一图总览你的实验" title="总览" description="从数据出发，循证据而行。" actions={<Button asChild><Link to={`${base}/waveform`}>打开波形<ArrowRight/></Link></Button>}/>
    {ws && <div className="flex items-center gap-3 mb-7"><ScientificStatus value={ws.scientific_status}/><span className="muted text-sm">{batteryId} · {experimentId}</span></div>}
    <div className="grid lg:grid-cols-[1.35fr_1fr] gap-7"><section className="panel"><p className="eyebrow">数据就绪</p><h2>从测量到洞察</h2>
      {quality.error ? <ErrorState error={quality.error} retry={()=>void quality.refetch()}/> : <><div className="data-row"><Battery className="data-icon" size={40}/><div className="flex-1"><h3>电气数据</h3><p className="text-sm muted">{q?.electrical ? `${numberText(q.electrical.records,0)} 条记录 · ${q.electrical.cycles} 个循环` : quality.isLoading ? "Loading…" : "尚无电气数据"}</p></div>{q?.electrical && <CheckCircle2 size={17} className="text-primary"/>}</div>
      <div className="data-row"><Waves className="data-icon" size={40}/><div className="flex-1"><h3>超声数据</h3><p className="text-sm muted">{q?.ultrasound ? `${numberText(q.ultrasound.frames,0)} 帧波形` : "尚无超声数据"}</p></div>{q?.ultrasound && <CheckCircle2 size={17} className="text-primary"/>}</div></>}
      <div className="data-row"><Link2 className="data-icon" size={40}/><div><h3>时间同步</h3><p className="text-sm muted">{status.data?.data.synchronization.validated_sync ? "已验证同步" : "未验证 · 时间基准为暂定"}</p></div></div><Button variant="link" asChild className="px-0 mt-2"><Link to={`${base}/advanced/data`}>查看数据质量<ArrowRight/></Link></Button>
    </section><section className="panel"><p className="eyebrow">可探索内容</p><h2>分析就绪</h2><div className="data-row"><div className="flex-1"><h3>参考 SOC</h3><p className="text-sm muted">基于电气数据的回溯参考</p></div><Badge variant="secondary">{status.data?.data.soc.status ? "仅供参考" : "检查数据"}</Badge></div>
      <div className="data-row"><div><h3>幅值</h3><p className="text-sm muted">查看波形幅值与可用特征。</p></div></div><div className="data-row"><div><h3>飞行时间 TOF</h3><p className="text-sm muted mb-3">需要采样频率才能进行绝对时间测量。</p><ParameterDialog/></div></div><p className="text-xs muted mt-4">SOH 数据尚不支持建模评估。</p></section></div>
    <section className="mt-9"><p className="eyebrow">最新发现</p><div className="finding"><h2>{comparison.beats===false ? "当前没有任何模型跑赢 Dummy 基准。" : comparison.beats===true ? "有模型在本次评估中跑赢了 Dummy。" : "你的下一个发现从一帧波形开始。"}</h2><p className="muted mt-3">{comparison.dummy ? `Dummy 均值宏观 MAE：${numberText(comparison.dummy.value)}%。这是一个有限的、仅针对本实验的评估。` : "先查看可用信号，再探索它们与参考 SOC 的关系。"}</p></div><div className="flex gap-3"><Button variant="outline" asChild><Link to={`${base}/analysis`}>继续分析<ArrowRight/></Link></Button>{comparison.dummy && <Button variant="ghost" asChild><Link to={`${base}/models`}>查看模型对比</Link></Button>}</div></section>
    <ScopeNote/>{ws?.limitations_registry?.length ? <details className="mt-5"><summary>研究限制</summary><ul className="list-disc pl-5 text-sm muted">{ws.limitations_registry.map(l=><li key={l.code}>{l.description}</li>)}</ul></details> : null}
  </>;
}
