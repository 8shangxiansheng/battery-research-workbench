import { lazy, Suspense, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, Waves, Battery, MessageSquare } from "lucide-react";
import { client } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { PageHeader, LoadingState, ErrorState, ScopeNote } from "../../components/workbench/shared";
import { ParameterDialog } from "../../components/workbench/ParameterDialog";
import { useAssistant } from "../../components/workbench/AssistantContext";
import { modelComparison, numberText } from "../../lib/presentation";
import { overviewNextStep } from "../../lib/overview-workflow";

const ElectricalMiniView = lazy(() => import("../../components/workbench/OverviewSignals").then(m => ({ default: m.ElectricalMiniView })));
const UltrasoundMiniView = lazy(() => import("../../components/workbench/OverviewSignals").then(m => ({ default: m.UltrasoundMiniView })));

export function OverviewPage() {
  const { batteryId = "", experimentId = "" } = useParams();
  const base = `/experiments/${batteryId}/${experimentId}`;
  const [repair, setRepair] = useState<string | null>(null);
  const assistant = useAssistant();
  const summary = useQuery({ queryKey: ["workspace-summary", batteryId, experimentId], queryFn: () => client.getWorkspaceSummary(batteryId, experimentId) });
  const quality = useQuery({ queryKey: ["data-quality", batteryId, experimentId], queryFn: () => client.getDataQuality(batteryId, experimentId) });
  const status = useQuery({ queryKey: ["status", batteryId, experimentId], queryFn: () => client.getStatus(batteryId, experimentId) });
  const results = useQuery({ queryKey: ["results", batteryId, experimentId], queryFn: () => client.getResults(batteryId, experimentId) });
  if (summary.isPending) return <LoadingState/>;
  if (summary.isError) return <ErrorState error={summary.error} retry={() => void summary.refetch()}/>;
  const ws = summary.data?.data; const q = quality.data?.data; const s = status.isError ? undefined : status.data?.data;
  const comparison = modelComparison(results.isError ? [] : results.data?.data ?? []);
  const next = overviewNextStep(s, ws, comparison.macro.length > 0);
  const synced = s?.synchronization.validated_sync === true;
  const tofReady = !!s && ["AVAILABLE", "READY"].includes(s.tof.status);
  const ask = (question: string) => { setRepair(null); assistant.ask(question); };
  return <div className="overview-workbench">
    <PageHeader eyebrow="实验 / OVERVIEW" title="实验进度与下一步" description={`${batteryId} / ${experimentId}`}/>
    <section className={`pipeline-card ${next.kind === "resolve" ? "state-warning" : ""}`} aria-label="实验主工作流">
      <div className="flex items-center gap-4 justify-between flex-wrap"><div><p className="eyebrow">当前卡点</p><h2>{next.kind === "resolve" ? "先补齐测量依据，再推进定量分析" : next.label}</h2><p className="text-sm muted mt-2">原始波形仍可查看；绝对 TOF 与跨模态分析须满足各自前置条件。</p></div>
        {next.kind === "navigate" ? <Button asChild data-testid="overview-primary"><Link to={`${base}/${next.route}`}>{next.label}<ArrowRight/></Link></Button> : <Button data-testid="overview-primary" disabled={next.kind === "unknown"} onClick={() => setRepair("前置条件")}>{next.label}<ArrowRight/></Button>}
      </div>
      <ol className="pipeline-stages" aria-label="分析流程">{["数据与前置条件", "波形与闸门", "特征与相关性", "建模评估", "报告与证据"].map((label, i) => <li key={label}><span className="font-mono">0{i + 1}</span>{label}</li>)}</ol>
      {status.isError && <ErrorState error={status.error} retry={() => void status.refetch()}/>}
    </section>
    <div className="overview-grid">
      <section className="panel signal-card"><div className="flex justify-between items-center"><h2 className="flex items-center gap-2"><Battery size={18}/>电气数据</h2><Badge className={q?.electrical ? "state-success" : ""} variant="outline">{q?.electrical ? "已解析" : quality.isPending ? "检查中" : "待检查"}</Badge></div>
        <p className="signal-stat">{numberText(q?.electrical?.records, 0)} <span>条记录 · {numberText(q?.electrical?.cycles, 0)} 个循环</span></p>
        <Suspense fallback={<p className="signal-placeholder">加载图表…</p>}><ElectricalMiniView batteryId={batteryId} experimentId={experimentId}/></Suspense>
        <Button variant="ghost" asChild className="mt-2"><Link to={`${base}/advanced/data`}>查看数据质量<ArrowRight/></Link></Button>
      </section>
      <section className="panel signal-card"><div className="flex justify-between items-center"><h2 className="flex items-center gap-2"><Waves size={18}/>超声数据</h2><Badge className={q?.ultrasound ? "state-success" : ""} variant="outline">{q?.ultrasound ? "已解析" : quality.isPending ? "检查中" : "待检查"}</Badge></div>
        <p className="signal-stat">{numberText(q?.ultrasound?.frames, 0)} <span>帧 · 原始幅值 / a.u.</span></p>
        <Suspense fallback={<p className="signal-placeholder">加载图表…</p>}><UltrasoundMiniView batteryId={batteryId} experimentId={experimentId}/></Suspense>
        <Button variant="ghost" asChild className="mt-2"><Link to={`${base}/waveform`}>打开波形<ArrowRight/></Link></Button>
      </section>
      <section className="panel readiness-card"><h2>分析前置条件</h2><p className="text-xs muted mt-1">按分析目标分别判断，不将保存视为验证。</p>
        <div className="readiness-row"><div><h3>时间基准</h3><p className="text-xs muted">{s ? s.synchronization.timebase_status : "状态待获取"}</p></div><Button variant="ghost" className={synced ? "state-success" : "state-warning"} onClick={() => setRepair("时间基准")}>{synced ? "验证通过" : "检查同步依据"}</Button></div>
        <div className="readiness-row"><div><h3>飞行时间 TOF</h3><p className="text-xs muted">{tofReady ? "API 已提供可用状态" : "采样率、时间零点与检测器待验证"}</p></div>{tofReady ? <Badge className="state-success">可用</Badge> : <ParameterDialog/>}</div>
        <div className="readiness-row"><div><h3>参考 SOC</h3><p className="text-xs muted" title={s?.soc.reason}>{s?.soc.status === "RETROSPECTIVE_SOC_REFERENCE" ? "回溯参考，不等于真实 SOC" : "依据以后端状态为准"}</p></div><Badge variant="outline">{s?.soc.status === "RETROSPECTIVE_SOC_REFERENCE" ? "回溯参考" : s?.soc.status ?? "未知"}</Badge></div>
        <div className="readiness-row"><div><h3>SOH 评估</h3><p className="text-xs muted">{s?.soh.status === "NOT_READY" ? "评估依据未就绪，不阻塞 SOC 探索" : s?.soh.status ?? "状态待获取"}</p></div><Button variant="ghost" onClick={() => setRepair("SOH 数据依据")}>查看要求</Button></div>
        <Button variant="ghost" className="px-0 text-xs" onClick={() => ask(`请解释当前实验的分析阻断。同步：${s?.synchronization.timebase_status ?? "UNKNOWN"}；TOF：${s?.tof.reason ?? "UNKNOWN"}；SOH：${s?.soh.reason ?? "UNKNOWN"}。`)}><MessageSquare size={14}/>携带阻断上下文询问助手</Button>
      </section>
    </div>
    {quality.isError && <ErrorState error={quality.error} retry={() => void quality.refetch()}/>}
    <section className={`panel model-diagnostic ${comparison.beats === false ? "state-warning" : ""}`} aria-label="模型诊断">
      <div className="flex justify-between gap-6 items-start flex-wrap"><div><p className="eyebrow">模型基准 / 科学结论</p><h2>{comparison.beats === false ? "当前没有任何模型跑赢 Dummy 基准。" : comparison.beats === true ? "有模型在本次评估中跑赢了 Dummy。" : "尚无可比较的模型结果"}</h2><p className="text-sm mt-2">{comparison.dummy ? <>Dummy 宏观 MAE：<strong className="font-mono text-lg">{numberText(comparison.dummy.value)} {comparison.dummy.units === "percent" ? "%" : comparison.dummy.units}</strong> · 仅限当前同口径评估。</> : "先复核特征与划分依据，不将尚未评估当成模型失败。"}</p></div><Button variant="ghost" asChild><Link to={`${base}/models`}>查看模型对比<ArrowRight/></Link></Button></div>
      {results.isError && <ErrorState error={results.error} retry={() => void results.refetch()}/>}
      <details className="mt-3"><summary>排查建议与下一步</summary><ul className="list-disc pl-5 text-sm space-y-1"><li>在 TRAIN 内检查特征共线性、缺失比例和充放电分布，不用 HELD_OUT 反复挑选特征。</li><li>检查同步误差及参考 SOC 来源，确认训练与评估口径一致。</li><li>补充独立电池和循环，而非仅增加同一循环内的相邻帧。</li></ul><div className="flex gap-2 flex-wrap mt-3"><Button variant="ghost" asChild><Link to={`${base}/analysis`}>复核特征配置</Link></Button><Button variant="ghost" onClick={() => setRepair("重新配置超参数")}>重新配置超参数</Button><Button variant="ghost" onClick={() => ask(`请提供模型诊断清单。Dummy MAE：${numberText(comparison.dummy?.value)} ${comparison.dummy?.units ?? ""}；是否超过基准：${String(comparison.beats)}。请区分已知结果与待验证假设。`)}><MessageSquare size={14}/>询问助手</Button></div></details>
    </section>
    <ScopeNote/>
    <Sheet open={repair !== null} onOpenChange={open => { if (!open) setRepair(null); }}><SheetContent className="sm:max-w-[480px] overflow-y-auto"><SheetHeader><SheetTitle>{repair}</SheetTitle><SheetDescription>当前实验的依据、限制与可执行操作；不会自动修改科学结论。</SheetDescription></SheetHeader><div className="space-y-5 py-6">
      {repair === "重新配置超参数" ? <><Badge className="state-warning">当前 API 不支持调优</Badge><p>服务只提供固定基线模型，尚无超参数配置或训练调优接口。不能将点击此入口视为已配置或已提交训练。</p><Button variant="outline" asChild><Link to={`${base}/analysis`}>先复核特征与 TRAIN 划分</Link></Button></> : <>
        {repair !== "SOH 数据依据" && <><h3>1. 采样频率</h3><p className="text-sm muted">提供仪器配置记录。保存后刷新就绪状态；未验证时仍保留阻断。</p><ParameterDialog label="填写采样频率"/><h3>2. 时间基准与同步</h3><p className="text-sm">{synced ? "后端报告同步验证通过。" : "需要逐资产时间锚点、时区与校准依据，并重新运行同步验证。当前 API 没有校准文件上传或时间锚点更新接口。"}</p><Button variant="outline" onClick={() => void status.refetch()} disabled={status.isFetching}>{status.isFetching ? "检查中…" : "重新检查后端状态"}</Button><p role="status" className={synced ? "state-success p-3" : "state-warning p-3"}>{synced ? "验证通过" : "尚未验证；原始波形查看不受影响。"}</p></>}
        <h3>SOH 所需依据</h3><p className="text-sm">{s?.soh.reason ?? "后端状态未知"}。参考容量及更多独立老化状态需要可靠来源；单次输入容量不会自动解除 SOH 建模限制。</p><Button variant="ghost" asChild><Link to={`${base}/advanced/parameters`}>查看已有参数与来源</Link></Button>
      </>}
    </div></SheetContent></Sheet>
  </div>;
}
