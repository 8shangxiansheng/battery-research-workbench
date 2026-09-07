import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams, Link } from "react-router-dom";
import { ArrowRight, Check, FlaskConical, ShieldCheck } from "lucide-react";
import { client, type FeatureInfo } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { Badge } from "../../components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { PageHeader, LoadingState, ErrorState, ScopeNote } from "../../components/workbench/shared";
import { ParameterDialog } from "../../components/workbench/ParameterDialog";
import { displayName } from "../../lib/presentation";

const CORE=["amplitude_a_u","tof_us","wave_speed_m_s"];
export function FeatureCard({feature,selected,toggle}:{feature:FeatureInfo;selected:boolean;toggle:()=>void}) {
  const available=feature.availability==="AVAILABLE";
  const reason=feature.feature_name==="tof_us" ? "Sampling rate required" : feature.feature_name==="wave_speed_m_s" ? "Acoustic path and capability required" : "Not available in this experiment";
  return <div className="feature-card" data-selected={selected}><div className="flex items-start gap-3"><Checkbox aria-label={`Select ${displayName(feature.feature_name)}`} checked={selected} disabled={!available} onCheckedChange={toggle}/><div className="flex-1"><h3>{displayName(feature.feature_name)}</h3><p className="text-xs muted mt-1">{available ? "Available for inspection" : reason}</p></div>{selected && <Check size={15} className="text-primary"/>}</div><div className="mt-5">{available ? <Badge variant="secondary">Available</Badge> : feature.feature_name==="tof_us" ? <ParameterDialog/> : <Badge variant="outline">Unavailable</Badge>}</div></div>;
}
export function AnalysisWorkbench() {
  const {batteryId="",experimentId=""}=useParams();
  const [mode,setMode]=useState<"EXPLORATORY_FULL_DATA"|"TRAIN_ONLY_ML_SAFE">("EXPLORATORY_FULL_DATA");
  const [selected,setSelected]=useState<string[]>([]); const [action,setAction]=useState<"analysis"|"dataset"|null>(null); const [analysisId,setAnalysisId]=useState<string|null>(null);
  const features=useQuery({queryKey:["features",batteryId,experimentId],queryFn:()=>client.listFeatures(batteryId,experimentId)});
  const analysis=useQuery({queryKey:["feature-analysis",analysisId],queryFn:()=>client.getFeatureAnalysis(analysisId!),enabled:!!analysisId});
  const run=useMutation({mutationFn:()=>client.createFeatureAnalysis({battery_id:batteryId,experiment_id:experimentId,analysis_mode:mode,target:"soc_reference_percent",candidate_features:selected}),onSuccess:r=>{setAction(null);setAnalysisId(r.data.analysis_id);}});
  const dataset=useMutation({mutationFn:()=>client.createDataset({battery_id:batteryId,experiment_id:experimentId,dataset_family:"SOC",target:"soc_reference_percent",selected_features:selected}),onSuccess:()=>setAction(null)});
  const all=features.data?.data.features??[];
  const core=CORE.map(name=>all.find(f=>f.feature_name===name)??{feature_name:name,availability:"UNAVAILABLE",role:null,gate_id:null,tof_definition_id:null,missing_reason:null});
  const more=all.filter(f=>!CORE.includes(f.feature_name));
  function toggle(name:string){setSelected(prev=>prev.includes(name)?prev.filter(n=>n!==name):[...prev,name]);setAnalysisId(null);dataset.reset();}
  if(features.isLoading) return <LoadingState/>;
  if(features.error) return <ErrorState error={features.error} retry={()=>void features.refetch()}/>;
  return <><PageHeader eyebrow="Understand your signals" title="Analysis" description="Explore relationships with reference SOC, or prepare a leakage-safe selection."/>
    <fieldset className="mb-8"><legend className="font-medium mb-3">Analysis mode</legend><div className="grid md:grid-cols-2 gap-4">
      {([{value:"EXPLORATORY_FULL_DATA",title:"Explore relationships",description:"Uses all available data for scientific exploration.",icon:FlaskConical},{value:"TRAIN_ONLY_ML_SAFE",title:"Select features for modeling",description:"Uses training data only to avoid leakage.",icon:ShieldCheck}] as const).map(m=><label key={m.value} className={`panel flex items-start gap-3 cursor-pointer ${mode===m.value?"!border-primary !bg-[#f3f7f6]":""}`}><input type="radio" name="analysis-mode" className="mt-1 accent-[#385c66]" checked={mode===m.value} onChange={()=>{setMode(m.value);setAnalysisId(null);dataset.reset();}}/><div><h3 className="flex gap-2 items-center"><m.icon size={17}/>{m.title}</h3><p className="text-sm muted mt-2">{m.description}</p></div></label>)}
    </div></fieldset>
    <div className="flex justify-between items-center mb-4"><h2>Core features</h2><span className="text-sm muted">{selected.length} selected</span></div><div className="grid md:grid-cols-3 gap-4">{core.map(f=><FeatureCard key={f.feature_name} feature={f} selected={selected.includes(f.feature_name)} toggle={()=>toggle(f.feature_name)}/>)}</div>
    <details className="mt-4 mb-8" data-testid="more-features"><summary>More features · {more.length} available entries</summary><div className="grid md:grid-cols-3 gap-4 mt-3">{more.map((f,i)=><FeatureCard key={`${f.feature_name}-${f.gate_id}-${i}`} feature={f} selected={selected.includes(f.feature_name)} toggle={()=>toggle(f.feature_name)}/>)}</div></details>
    <section className="panel"><div className="flex flex-wrap gap-4 justify-between items-center"><div><h2>{mode==="EXPLORATORY_FULL_DATA"?"Explore without overclaiming":"Keep selection inside the training set"}</h2><p className="muted text-sm mt-2">{mode==="EXPLORATORY_FULL_DATA"?"Exploratory rankings cannot be reused as unbiased modeling selections.":"Held-out groups must remain untouched during feature selection and fitting."}</p></div><Button disabled={!selected.length} onClick={()=>{run.reset();setAction("analysis");}}>Review analysis<ArrowRight/></Button></div>
      <p className="text-xs muted mt-5">The current service resolves an analysis specification. Detailed correlations and rankings are shown only when provided by the API.</p>
      {analysisId && <div role="status" className="notice mt-4">{analysis.isLoading?"Checking analysis availability…":analysis.error?"Specification resolved, but analysis results are not available. No values or ranking have been inferred.":"Analysis is available. This API currently provides status only; correlation details are not exposed."}</div>}
      <div className="mt-5 flex flex-wrap gap-3 items-center"><Button variant="outline" disabled={mode!=="TRAIN_ONLY_ML_SAFE" || !selected.length || analysis.data?.data.status!=="AVAILABLE"} onClick={()=>{dataset.reset();setAction("dataset");}}>Build dataset with {selected.length} features</Button><Button variant="link" asChild><Link to={`/experiments/${batteryId}/${experimentId}/advanced/runs`}>Review pending scientific actions</Link></Button></div>
      <p className="text-xs muted mt-2">Dataset creation requires an available ML-safe analysis and explicit confirmation. Backend eligibility remains authoritative.</p>{dataset.isSuccess && <p role="status" className="mt-3">Dataset request completed. Review the grouped split in Advanced.</p>}
    </section><ScopeNote/>
    <Dialog open={action!==null} onOpenChange={open=>{if(!open)setAction(null);}}><DialogContent><DialogHeader><DialogTitle>{action==="dataset"?"Build selected dataset":"Confirm analysis request"}</DialogTitle><DialogDescription>{batteryId} / {experimentId} · {mode==="TRAIN_ONLY_ML_SAFE"?"Training-only selection":"Exploratory relationships"}. This scientific action uses the selected inputs below.</DialogDescription></DialogHeader><ul className="list-disc pl-5">{selected.map(n=><li key={n}>{displayName(n)}</li>)}</ul><p className="text-sm muted">Your confirmation authorizes this request only. No automatic feature selection or model training will occur.</p>{(run.error||dataset.error) && <p role="alert">The service could not accept this request. Review prerequisites and retry.</p>}<DialogFooter><Button variant="outline" onClick={()=>setAction(null)}>Cancel</Button><Button disabled={run.isPending||dataset.isPending} onClick={()=>action==="dataset"?dataset.mutate():run.mutate()}>Confirm request</Button></DialogFooter></DialogContent></Dialog>
  </>;
}
