import { lazy, Suspense, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Hand, MousePointer2, Plus, RotateCcw, ZoomIn } from "lucide-react";
import { client } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Badge } from "../../components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { PageHeader, LoadingState, ErrorState, EmptyState, BlockedValue, ScopeNote } from "../../components/workbench/shared";
import { ParameterDialog } from "../../components/workbench/ParameterDialog";
import { numberText } from "../../lib/presentation";
const WaveformPlot = lazy(()=>import("../../components/workbench/WaveformPlot"));

export function WaveformWorkbench() {
  const {batteryId="",experimentId=""}=useParams(); const qc=useQueryClient();
  const [position,setPosition]=useState(0); const [mode,setMode]=useState<"zoom"|"pan"|"select">("zoom"); const [reset,setReset]=useState(0);
  const [draft,setDraft]=useState<{start:number;end:number}|null>(null); const [confirm,setConfirm]=useState(false); const [name,setName]=useState(""); const [message,setMessage]=useState("");
  const frames=useQuery({queryKey:["waveform-frames",batteryId,experimentId],queryFn:()=>client.listWaveformFrames(batteryId,experimentId)});
  const frame=frames.data?.data.frames[position];
  const preview=useQuery({queryKey:["waveform-frame",batteryId,experimentId,frame?.frame_index],queryFn:()=>client.getWaveformFrame(batteryId,experimentId,frame!.frame_index,1000),enabled:!!frame});
  const gates=useQuery({queryKey:["gates",batteryId,experimentId],queryFn:()=>client.listGates(batteryId,experimentId)});
  const events=useQuery({queryKey:["events-preview",batteryId,experimentId],queryFn:()=>client.getMeasurementEvents(batteryId,experimentId,50)});
  const status=useQuery({queryKey:["status",batteryId,experimentId],queryFn:()=>client.getStatus(batteryId,experimentId)});
  const commit=useMutation({mutationFn:()=>client.createGate({battery_id:batteryId,experiment_id:experimentId,gate_name:name.trim() || "Selected region",start_sample:draft!.start,end_sample:draft!.end,waveform_length:preview.data!.data.waveform_length}), onSuccess:r=>{setConfirm(false);setDraft(null);setName("");setMessage(r.data.reuse_status==="REUSED"?"已复用现有闸门。":"闸门已保存到本实验。");void qc.invalidateQueries({queryKey:["gates",batteryId,experimentId]});}});
  function select(start:number,end:number){const max=(preview.data?.data.waveform_length??1)-1; const s=Math.max(0,Math.min(start,max));const e=Math.max(s,Math.min(end,max));if(e>s){setDraft({start:s,end:e});setMessage("");}}
  function changePosition(next:number){setPosition(next);setDraft(null);setMessage("");}
  if(frames.isLoading) return <LoadingState/>;
  if(frames.error) return <ErrorState error={frames.error} retry={()=>void frames.refetch()}/>;
  if(!frames.data?.data.frames.length) return <EmptyState title="尚无波形数据" to={`/experiments/${batteryId}/${experimentId}/advanced/data`} action="查看实验数据">导入并处理超声数据后即可浏览波形。</EmptyState>;
  const matches=events.data?.data.events.filter(e=>e.frame_index_raw===frame?.frame_index)??[];
  const unique=(frames.data.data.frames.filter(f=>f.frame_index===frame?.frame_index).length===1 && matches.length===1) ? matches[0] : undefined;
  const tof=status.data?.data.tof; const tofAvailable=tof?.status==="AVAILABLE" || tof?.status==="READY";
  return <><PageHeader eyebrow="信号工作台" title="波形与闸门" description="探索信号，框选区域即可创建闸门。" actions={<Button onClick={()=>setMode("select")}><Plus/>添加闸门</Button>}/>
    <section className="panel !p-0 overflow-hidden"><div className="flex flex-wrap gap-4 items-center border-b px-5 py-4"><div className="flex gap-2 items-center"><Button variant="outline" size="icon" aria-label="上一帧" disabled={position===0} onClick={()=>changePosition(position-1)}><ChevronLeft/></Button><label className="flex items-center gap-2 text-sm">Frame<Input aria-label="帧位置" className="!w-20" type="number" min={1} max={frames.data.data.frames.length} value={position+1} onChange={e=>changePosition(Math.min(frames.data!.data.frames.length-1,Math.max(0,Number(e.target.value)-1)))}/></label><span className="muted text-xs">共 {numberText(frames.data.data.frames.length,0)} 帧</span><Button variant="outline" size="icon" aria-label="下一帧" disabled={position===frames.data.data.frames.length-1} onClick={()=>changePosition(position+1)}><ChevronRight/></Button></div><div className="ml-auto flex gap-4 text-xs muted"><span>循环 {unique?.cycle_index_raw??"—"}</span><span>工步 {unique?.step_index_raw??"—"}</span><span>参考 SOC {numberText(unique?.soc_reference_percent)}%</span></div></div>
      <div className="flex flex-wrap items-center gap-2 px-5 pt-4" role="toolbar" aria-label="波形控制">{([{value:"zoom",label:"缩放",icon:ZoomIn},{value:"pan",label:"平移",icon:Hand},{value:"select",label:"框选闸门",icon:MousePointer2}] as const).map(t=><Button key={t.value} variant={mode===t.value?"secondary":"ghost"} size="sm" aria-pressed={mode===t.value} onClick={()=>setMode(t.value)}><t.icon/>{t.label}</Button>)}<Button variant="ghost" size="sm" onClick={()=>setReset(v=>v+1)}><RotateCcw/>重置视图</Button><span className="ml-auto text-xs muted">包络暂不可用</span></div>
      <div className="plot-wrap" data-testid="waveform-plot" aria-label="波形图">{preview.error ? <ErrorState error={preview.error} retry={()=>void preview.refetch()}/> : preview.data ? <Suspense fallback={<LoadingState/>}><WaveformPlot preview={preview.data.data} gates={gates.data?.data.gates??[]} draft={draft} mode={mode} reset={reset} onSelect={select}/></Suspense> : <LoadingState/>}</div>
      <div className="px-6 py-3 border-t text-xs muted flex gap-2 items-center"><Badge variant="outline">采样点</Badge>{mode==="select" ? "在信号上横向拖拽即可提议一个闸门。" : "滚轮缩放，双击恢复视图。"} 物理时间轴尚未验证。</div>
    </section>
    {draft && <div className="notice mt-4 items-center"><div className="flex-1"><h3>新闸门选区</h3><p className="text-sm">当前为草稿，确认后才会保存到实验。</p></div><Button variant="ghost" onClick={()=>setDraft(null)}>丢弃</Button><Button onClick={()=>{setConfirm(true);commit.reset();}}>检查闸门</Button></div>}
    {message && <p role="status" className="notice mt-4">{message}</p>}
    <div className="grid md:grid-cols-3 panel !p-0 mt-6"><BlockedValue name="幅值" reason="将鼠标悬停在波形上可查看采样点幅值。"/><BlockedValue name="飞行时间 TOF" value={tofAvailable ? tof?.value : null} unit="µs" reason={tofAvailable ? "来自 API 结果" : "需要先提供采样频率"} action={!tofAvailable && <ParameterDialog/>}/><BlockedValue name="波速" reason="需要声程长度与后端能力支持" action={<Button variant="link" size="sm" asChild className="px-0"><Link to={`/experiments/${batteryId}/${experimentId}/advanced/parameters`}>Review parameters</Link></Button>}/></div>
    <div className="mt-6 flex flex-wrap items-center gap-3"><h3>已保存的闸门</h3>{gates.data?.data.gates.map((g,i)=><Badge variant="secondary" key={g.gate_id}>{g.gate_name??`闸门 ${i+1}`}</Badge>)}{gates.data?.data.gates.length===0 && <span className="muted text-sm">在上方框选你的第一个区域。</span>}{gates.error && <span role="status">已保存闸门暂不可用，请刷新页面重试。</span>}</div>
    <details className="mt-5"><summary>高级波形细节与键盘闸门选择</summary><p className="muted text-xs">仅当 API 事件预览中存在唯一匹配时才显示帧上下文。充放电阶段与包络信息此接口未提供。</p><p className="text-xs muted">峰峰值 TOF：暂不可用 · 绝对到达时间：需要已验证的时序</p><div className="flex gap-3 items-end mt-3"><label className="field">起始采样点<Input aria-label="闸门起始采样点" type="number" min={0} value={draft?.start??0} onChange={e=>setDraft({start:Number(e.target.value),end:draft?.end??1})}/></label><label className="field">结束采样点<Input aria-label="闸门结束采样点" type="number" min={1} value={draft?.end??1} onChange={e=>setDraft({start:draft?.start??0,end:Number(e.target.value)})}/></label><Button variant="outline" disabled={!draft || draft.end<=draft.start || draft.start<0 || draft.end>=(preview.data?.data.waveform_length??0)} onClick={()=>setConfirm(true)}>检查闸门</Button></div></details><ScopeNote/>
    <Dialog open={confirm} onOpenChange={setConfirm}><DialogContent><DialogHeader><DialogTitle>保存选定的闸门</DialogTitle><DialogDescription>将为 {batteryId} / {experimentId} 保存一个信号区域。不会计算新特征，也不会修改原始波形。</DialogDescription></DialogHeader><label className="field">闸门名称<Input value={name} onChange={e=>setName(e.target.value)} placeholder="例如：第一反射波"/></label><p className="text-sm muted">选定区间：{draft?.start}–{draft?.end} 采样点。后端会校验区间并分配唯一标识。</p>{commit.error && <p role="alert">闸门保存失败，请检查区间后重试。</p>}<DialogFooter><Button variant="outline" onClick={()=>setConfirm(false)}>取消</Button><Button disabled={commit.isPending || !draft} onClick={()=>commit.mutate()}>{commit.isPending?"保存中…":"保存闸门"}</Button></DialogFooter></DialogContent></Dialog>
  </>;
}
