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
  return <><PageHeader eyebrow="Your experiment, at a glance" title="Overview" description="Start with the data. Follow the evidence." actions={<Button asChild><Link to={`${base}/waveform`}>Open waveform<ArrowRight/></Link></Button>}/>
    {ws && <div className="flex items-center gap-3 mb-7"><ScientificStatus value={ws.scientific_status}/><span className="muted text-sm">{batteryId} · {experimentId}</span></div>}
    <div className="grid lg:grid-cols-[1.35fr_1fr] gap-7"><section className="panel"><p className="eyebrow">Data readiness</p><h2>From measurements to insight</h2>
      {quality.error ? <ErrorState error={quality.error} retry={()=>void quality.refetch()}/> : <><div className="data-row"><Battery className="data-icon" size={40}/><div className="flex-1"><h3>Electrical</h3><p className="text-sm muted">{q?.electrical ? `${numberText(q.electrical.records,0)} records · ${q.electrical.cycles} cycles` : quality.isLoading ? "Loading…" : "No electrical data yet"}</p></div>{q?.electrical && <CheckCircle2 size={17} className="text-primary"/>}</div>
      <div className="data-row"><Waves className="data-icon" size={40}/><div className="flex-1"><h3>Ultrasound</h3><p className="text-sm muted">{q?.ultrasound ? `${numberText(q.ultrasound.frames,0)} waveform frames` : "No ultrasound data yet"}</p></div>{q?.ultrasound && <CheckCircle2 size={17} className="text-primary"/>}</div></>}
      <div className="data-row"><Link2 className="data-icon" size={40}/><div><h3>Time synchronization</h3><p className="text-sm muted">{status.data?.data.synchronization.validated_sync ? "Validated synchronization" : "Not validated · provisional timebase"}</p></div></div><Button variant="link" asChild className="px-0 mt-2"><Link to={`${base}/advanced/data`}>Review data quality<ArrowRight/></Link></Button>
    </section><section className="panel"><p className="eyebrow">What you can explore</p><h2>Analysis readiness</h2><div className="data-row"><div className="flex-1"><h3>Reference SOC</h3><p className="text-sm muted">Retrospective electrical reference</p></div><Badge variant="secondary">{status.data?.data.soc.status ? "Reference only" : "Check data"}</Badge></div>
      <div className="data-row"><div><h3>Amplitude</h3><p className="text-sm muted">Inspect waveform amplitude and available features.</p></div></div><div className="data-row"><div><h3>TOF</h3><p className="text-sm muted mb-3">Sampling rate required before absolute timing.</p><ParameterDialog/></div></div><p className="text-xs muted mt-4">SOH is not ready for model evaluation.</p></section></div>
    <section className="mt-9"><p className="eyebrow">Latest finding</p><div className="finding"><h2>{comparison.beats===false ? "No evaluated model outperformed Dummy Mean." : comparison.beats===true ? "A model outperformed Dummy in this evaluation." : "Your next finding starts with a waveform."}</h2><p className="muted mt-3">{comparison.dummy ? `Dummy Mean macro MAE: ${numberText(comparison.dummy.value)}%. This is a limited, within-study evaluation.` : "Inspect the available signals, then explore their relationship with reference SOC."}</p></div><div className="flex gap-3"><Button variant="outline" asChild><Link to={`${base}/analysis`}>Continue analysis<ArrowRight/></Link></Button>{comparison.dummy && <Button variant="ghost" asChild><Link to={`${base}/models`}>Review model comparison</Link></Button>}</div></section>
    <ScopeNote/>{ws?.limitations_registry?.length ? <details className="mt-5"><summary>Study limitations</summary><ul className="list-disc pl-5 text-sm muted">{ws.limitations_registry.map(l=><li key={l.code}>{l.description}</li>)}</ul></details> : null}
  </>;
}
