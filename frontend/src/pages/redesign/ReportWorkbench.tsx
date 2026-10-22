import { useState } from "react";
import { useQuery, useQueries, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, Download, FileText } from "lucide-react";
import { client, type TargetDefinition } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "../../components/workbench/shared";
import { SelectedFeaturesPanel } from "../../components/workbench/SelectedFeaturesPanel";
import { CorrelationDiagnosticPlot } from "../../components/workbench/CorrelationDiagnosticPlot";
import { displayName, modelComparison } from "../../lib/presentation";
import { StaleBanner } from "./WorkbenchShell";
import { useWorkflowContext } from "../../hooks/useWorkflowContext";
import { partitionResultsByDataset } from "../../lib/result-freshness";

function electrochemicalPhaseLabel(scope: string): string {
  return ({ overall: "整体", charge: "充电", discharge: "放电", rest: "静置" } as Record<string, string>)[scope] ?? scope;
}

function TargetProvenanceAudit({
  target,
  targetId,
  label,
  isLoading,
  error,
}: {
  target: TargetDefinition | undefined;
  targetId: string;
  label: string;
  isLoading: boolean;
  error: Error | null;
}) {
  const testId = `report-${targetId === "temperature_c" ? "temperature" : "soh"}-provenance`;
  if (isLoading) return <p className="muted mt-2 text-xs" role="status" data-testid={testId}>正在读取 {label} 目标来源与 readiness…</p>;
  if (error) return <p className="text-destructive mt-2 text-xs" role="alert" data-testid={testId}>无法核对 {label} 目标来源：{error.message}。实时相关系数不代表该目标已经通过来源验证。</p>;
  if (!target) return <p className="muted mt-2 text-xs" role="status" data-testid={testId}>{label} 目标定义不可用；来源、粒度和 readiness 未核实。</p>;
  const provenance = target.provenance;
  return <details className="mt-2 rounded-md border p-2 text-xs" data-testid={testId}>
    <summary>查看 {label} 目标来源、粒度与不确定度</summary>
    <ul className="mt-2 space-y-1">
      <li>语义 {target.semantic_type}；readiness {target.readiness}；覆盖 {target.coverage.valid}/{target.coverage.total}{target.coverage.independent_states === undefined ? "" : `；不同状态 ${target.coverage.independent_states}`}</li>
      {target.limitation && <li>就绪限制：{target.limitation}</li>}
      <li>来源：{target.source}；单位 {target.unit}</li>
      <li>粒度 {provenance?.target_grain ?? "未提供"}；声明独立单位 {provenance?.independent_unit ?? "未提供"}（Battery 实体身份不由此字段核验）</li>
      <li>方法 {provenance?.method_id ?? "未提供"} · 版本 {provenance?.method_version ?? "未提供"}</li>
      {provenance?.definition && <li>定义：{provenance.definition}</li>}
      {!!provenance?.observed_channels?.length && <li>实际关联通道：{provenance.observed_channels.join("、")}</li>}
      <li>不确定度 {provenance?.uncertainty.status ?? "UNKNOWN"}：{provenance?.uncertainty.reason ?? "未提供不确定度来源"}</li>
    </ul>
    {provenance?.source_assets.length ? <details className="mt-2">
      <summary>来源 DataAsset 与文件校验信息（{provenance.source_assets.length} 项）</summary>
      <ul className="mt-1 space-y-1">{provenance.source_assets.map(asset => <li key={asset.asset_id}>
        {asset.asset_id} · {asset.source_reference ?? "路径未提供"} · SHA-256 <code>{asset.sha256}</code>
      </li>)}</ul>
    </details> : <p className="muted mt-2">来源 DataAsset 清单未提供。</p>}
    <p className="muted mt-2">以上是当前 Targets API 的来源与就绪声明，不代表冻结报告快照，也不单独证明测量真实性、校准有效性或跨电池独立性。</p>
  </details>;
}

export function ReportWorkbench() {
  const {batteryId="",experimentId=""}=useParams();const qc=useQueryClient(); const [confirm,setConfirm]=useState(false); const [exportError,setExportError]=useState(false);
  const wf = useWorkflowContext(batteryId, experimentId);
  const reports=useQuery({queryKey:["reports",batteryId,experimentId],queryFn:()=>client.listReports(batteryId,experimentId)});
  const limitations=useQuery({queryKey:["limitations",batteryId,experimentId],queryFn:()=>client.getLimitations(batteryId,experimentId)});
  const targetsQuery=useQuery({queryKey:["targets",batteryId,experimentId],queryFn:()=>client.listTargets(batteryId,experimentId)});
  const results=useQuery({queryKey:["results",batteryId,experimentId],queryFn:()=>client.getResults(batteryId,experimentId)});
  const create=useMutation({mutationFn:()=>client.createReport({battery_id:batteryId,experiment_id:experimentId}),onSuccess:()=>{setConfirm(false);void qc.invalidateQueries({queryKey:["reports",batteryId,experimentId]});}});
  const list=reports.data?.data??[]; const dated=list.filter(r=>typeof r.generated_at==="string").sort((a,b)=>String(b.generated_at).localeCompare(String(a.generated_at)));
  const report=dated[0]??list[0];
  const reportFreshness=report?.report_freshness as {status?:string;reasons?:string[]}|undefined;
  const reportFreshnessStatus=reportFreshness?.status??wf.data?.artifact_freshness.report;
  const reportIntegrityBlocked = reportFreshnessStatus === "INTEGRITY_BLOCKED" || wf.data?.artifact_freshness.report === "INTEGRITY_BLOCKED";
  const currentDatasetId = (wf.data?.steps.DATASET?.committed as { dataset_id?: string } | undefined)?.dataset_id ?? null;
  const resultPartition = partitionResultsByDataset(results.data?.data ?? [], currentDatasetId);
  const comparison=modelComparison(resultPartition.current);
  const canGenerateCurrentReport = comparison.macro.length > 0;
  const frozenFindings = Array.isArray(report?.scientific_findings)
    ? report.scientific_findings.filter((item): item is string => typeof item === "string")
    : [];
  const datasetIds=[...new Set(resultPartition.current.map(r=>r.dataset_id).filter((d): d is string => !!d))];
  const datasetArtifact=useQuery({queryKey:["artifact",currentDatasetId],queryFn:()=>client.getArtifact(currentDatasetId!),enabled:!!currentDatasetId});
  const committedFeatures=(wf.data?.steps.DATASET?.committed as {selected_features?:string[]}|undefined)?.selected_features;
  const manifestFields=(datasetArtifact.data?.data.fields??{}) as Record<string,unknown>;
  const selectedFeatures=committedFeatures??(manifestFields.selected_features as string[]|undefined)??[];
  const supportedCorrelationFeatures=selectedFeatures.filter((feature):feature is "SWA"|"BOTTOM_AMP"=>feature==="SWA"||feature==="BOTTOM_AMP");
  const unsupportedCorrelationFeatures=selectedFeatures.filter((feature)=>feature!=="SWA"&&feature!=="BOTTOM_AMP");
  const currentTargets=targetsQuery.data?.data.targets ?? [];
  const temperatureTarget=currentTargets.find(target=>target.target_id==="temperature_c");
  const sohTarget=currentTargets.find(target=>target.target_id==="soh_capacity_reference_percent");
  const correlationQueries=useQueries({queries:supportedCorrelationFeatures.map((feature)=>({
    queryKey:["feature-correlations",batteryId,experimentId,feature,300],
    queryFn:()=>client.getFeatureCorrelations(batteryId,experimentId,feature,300),
  }))});
  async function exportReport(){try {const r=await client.getReport(String(report?.report_id));const url=URL.createObjectURL(new Blob([JSON.stringify(r.data,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download="scientific-report.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch{setExportError(true);}}
  if(reports.isLoading || wf.isLoading || results.isLoading)return <LoadingState/>;if(reports.error)return <ErrorState error={reports.error} retry={()=>void reports.refetch()}/>;
  if(results.error)return <ErrorState error={results.error} retry={()=>void results.refetch()}/>;
  if(wf.error && !wf.data)return <ErrorState error={wf.error} retry={()=>void wf.refetch()}/>;
  return <><PageHeader eyebrow="可追溯的研究记录" title="科学报告" description="结论、限制，以及它们背后的证据。" actions={<Button variant="outline" disabled={!canGenerateCurrentReport} title={!canGenerateCurrentReport ? "当前数据集没有匹配的模型评估；请先完成当前模型运行。" : undefined} onClick={()=>{setConfirm(true);create.reset();}}><FileText/>生成报告</Button>}/>
    {wf.data && <StaleBanner freshness={wf.data.artifact_freshness} stepKey="REPORT" />}
    {report && ["STALE", "LEGACY", "SUPERSEDED", "MISSING"].includes(reportFreshnessStatus ?? "") && <p className="notice text-sm mb-4" role="status" data-testid="report-snapshot-stale">此报告是历史快照（{reportFreshnessStatus}），绑定的模型/数据集与当前提交状态不一致；其结论不代表当前数据集。{reportFreshness?.reasons?.length ? ` 原因：${reportFreshness.reasons.join("、")}` : ""}</p>}
    {!canGenerateCurrentReport && <p className="notice text-sm mb-4" role="status" data-testid="report-current-models-missing">当前数据集 {currentDatasetId ?? "尚未提交"} 没有匹配的模型评估。旧报告和其他数据集的指标不会用于新报告；请前往 Models 完成当前数据集评估。 <Link className="underline" to={`/experiments/${batteryId}/${experimentId}/models`}>查看模型与恢复步骤</Link></p>}
    {reportIntegrityBlocked ? <section className="panel border-amber-300 bg-amber-50/40 !p-6" role="alert" data-testid="report-integrity-blocked"><h2 className="text-xl">报告来源完整性未通过</h2><p className="muted mt-2">此报告依赖的数据来源清单无效或无法验证。为避免展示不可追溯的科学结论，已隐藏报告正文和导出内容。请先修复数据来源并重新运行相关分析。</p>{reportFreshness?.reasons?.length ? <p className="text-sm mt-3">原因：{reportFreshness.reasons.join("、")}</p> : null}<Link className="inline-flex items-center gap-2 underline mt-4" to={`/experiments/${batteryId}/${experimentId}/runs`}>查看运行记录与恢复步骤<ArrowRight/></Link></section> : !report ? <EmptyState title="还没有报告" to={`/experiments/${batteryId}/${experimentId}/models`} action="查看模型结果">先查看可用结果，再从既有科学产物生成报告。</EmptyState> : <article className="panel !p-8"><div className="flex justify-between gap-4 items-start"><div><p className="eyebrow">{dated.length?"最新报告":"可用报告"}</p><h2 className="text-2xl">实验研究摘要</h2><p className="muted text-sm mt-2">{batteryId} / {experimentId} · {report.generated_at ? String(report.generated_at) : "未提供生成时间"}</p></div><Button variant="outline" onClick={()=>void exportReport()}><Download/>导出 JSON</Button></div>
      <div className="mt-7 flex gap-2"><Badge variant="secondary">Reference SOC</Badge><Badge variant="outline">Limited evaluation</Badge></div>
      <div className="finding"><h2>{frozenFindings[0] ?? (comparison.beats===false?"Predictive advantage has not been demonstrated.":comparison.beats===true?"A model surpassed the baseline within this study.":"Review the available evidence before drawing a conclusion.")}</h2><p className="muted mt-3">{frozenFindings.length ? "Frozen scientific finding from this report snapshot." : "No frozen finding was available; showing the current experiment comparison."}</p></div>
      <h3 className="mt-7 mb-3">随本结果保留的限制</h3>{limitations.error?<ErrorState error={limitations.error} retry={()=>void limitations.refetch()}/>:<ul className="space-y-3 text-sm muted list-disc pl-5">{limitations.data?.data.limitations.map(l=><li key={l.code}>{l.description}</li>)}</ul>}
      <SelectedFeaturesPanel datasetId={datasetIds[0]} />
      <section className="panel mt-6 !p-5" data-testid="report-feature-summary">
        <h2>实时探索性关系诊断</h2>
        <p className="muted text-sm mt-1" data-testid="report-live-correlation-label">此处为基于当前 Dataset 所选特征的实时查询结果，不属于上方已冻结的报告快照；用于探索，不作确认性结论。</p>
        {!supportedCorrelationFeatures.length&&!datasetArtifact.isLoading&&<p className="notice text-sm mt-3" data-testid="report-correlation-unavailable">当前数据集所选特征没有可用的关系分析实现。此页面不会改用其他特征代替；目前支持 SWA 与 BOTTOM_AMP。</p>}
        {!!unsupportedCorrelationFeatures.length&&<p className="notice text-sm mt-3" data-testid="report-correlation-partial">以下已选特征没有可用的关系分析实现，未计算：{unsupportedCorrelationFeatures.join("、")}。目前支持 SWA 与 BOTTOM_AMP。</p>}
        {supportedCorrelationFeatures.map((feature,index)=>{
          const corr=correlationQueries[index];
          if (!corr) return null;
          return <section key={feature} data-testid={`report-feature-correlation-${feature}`} className="mt-5 border-t pt-4">
        <h3 className="font-medium">{feature} 与状态关系</h3>
        {corr.data?.data && <>
          <CorrelationDiagnosticPlot diagnostic={corr.data.data.soc_diagnostic_scatter} />
          <ul className="mt-3 space-y-2 text-sm list-disc pl-5">
            <li>{feature} 与 Reference SOC：Pearson {(() => { const r = corr.data!.data.soc.find(x => x.scope === "overall" && x.method === "pearson"); return r?.coefficient != null ? r.coefficient.toFixed(3) : "—"; })()}（overall）· 分层 charge/discharge/rest 由当前后端查询返回。</li>
            {!!corr.data.data.soc.length && <li><details data-testid="report-soc-estimate-audit"><summary>查看 SOC 各相关估计的样本与缺失审计（{corr.data.data.soc.length} 项）</summary><ul className="mt-2 space-y-1">{corr.data.data.soc.map((item) => <li key={item.analysis_id}>{item.method} · {item.scope}：r {item.coefficient?.toFixed(3) ?? "不可估计"}{item.ci_low != null && item.ci_high != null ? `（${item.interval_method ?? "—"} 95% 区间 ${item.ci_low.toFixed(3)} 至 ${item.ci_high.toFixed(3)}）` : "（区间不可估计）"}{item.p_value_adjusted != null ? ` · 校正后 p ${item.p_value_adjusted.toFixed(4)}（未校正 ${item.p_value_raw != null ? item.p_value_raw.toFixed(4) : "—"}；${item.multiplicity_correction ?? "—"}）` : ""}{item.replication_factor != null && item.replication_factor > 1 ? ` · 每单位 ${item.replication_factor.toFixed(1)} 行（${item.pseudo_replication_status ?? ""}：事件行为重复测量，不作为独立样本）` : ""} · 输入单位 {item.n_input_unit ?? "未提供"} · 有效配对 {item.n_valid}/{item.n_input} {item.n_valid_unit ?? "FEATURE_STATE_PAIR"} · 声明分组 {item.independent_group_count ?? "未提供"} {item.independent_unit ?? ""}（组身份 {item.group_identity_status ?? "NOT_ASSESSED"}） · 特征缺失 {item.missing_feature_count}、状态缺失 {item.missing_state_count}、同步排除 {item.excluded_ineligible_count} · 区间 {corr.data!.data.inference_assessment.confidence_interval.status} · {item.status}{item.limitations.length ? ` · ${item.limitations.join("；")}` : ""}</li>)}</ul><p className="muted text-xs mt-2">区间为 Fisher-z 解析近似，p 值仅在当前声明的 {corr.data.data.soc.length} 项族内做 Benjamini-Hochberg 校正，并保留未校正值对照；事件行为重复测量，这些仍是探索性描述，不构成确认性推断。混杂调整未完成预声明方案前不估计。</p></details></li>}
        {corr.data.data.soc_battery_decomposition && <li data-testid="report-battery-decomposition">Battery 分层（声明 Battery ID 分组 {corr.data.data.soc_battery_decomposition.declared_battery_group_count ?? corr.data.data.soc_battery_decomposition.n_batteries} 组；物理电池身份未独立审核；{corr.data.data.soc_battery_decomposition.n_events}/{corr.data.data.soc_battery_decomposition.n_input_events} 个有效/输入事件；特征缺失 {corr.data.data.soc_battery_decomposition.missing_feature_count}、状态缺失 {corr.data.data.soc_battery_decomposition.missing_state_count}、同步排除 {corr.data.data.soc_battery_decomposition.excluded_ineligible_count}；描述性，无区间/显著性推断）：组内 {corr.data.data.soc_battery_decomposition.within_battery.coefficient?.toFixed(3) ?? "不可估计"}；组间 {corr.data.data.soc_battery_decomposition.between_battery.coefficient?.toFixed(3) ?? "不可估计"}。{corr.data.data.soc_battery_decomposition.status === "INSUFFICIENT_BATTERY_GROUPS" ? "声明 Battery ID 组数不足，不能估计组间关系。" : corr.data.data.soc_battery_decomposition.interpretation === "BETWEEN_WITHIN_DIRECTION_DISAGREEMENT" ? "组间与组内方向相反，整体相关可能误导。" : ""}{corr.data.data.soc_battery_decomposition.limitations.length ? ` 限制：${corr.data.data.soc_battery_decomposition.limitations.join("；")}` : ""}</li>}
            {corr.data.data.soc_cycle_decomposition && <li data-testid="report-cycle-decomposition">Cycle 组内/组间诊断（{corr.data.data.soc_cycle_decomposition.n_cycle_groups} 个完整 Battery/Experiment/Cycle 组；有效事件 {corr.data.data.soc_cycle_decomposition.n_events}/{corr.data.data.soc_cycle_decomposition.n_input_events}；缺失特征 {corr.data.data.soc_cycle_decomposition.missing_feature_count}、状态 {corr.data.data.soc_cycle_decomposition.missing_state_count}、同步排除 {corr.data.data.soc_cycle_decomposition.excluded_ineligible_count}；描述性，不作独立电池推断）：组内 {corr.data.data.soc_cycle_decomposition.within_cycle.coefficient?.toFixed(3) ?? "不可估计"}；组间 {corr.data.data.soc_cycle_decomposition.between_cycle.coefficient?.toFixed(3) ?? "不可估计"}。{corr.data.data.soc_cycle_decomposition.status === "INSUFFICIENT_CYCLE_GROUPS" ? "完整 Cycle 组不足 3 个，不计算组间系数。" : corr.data.data.soc_cycle_decomposition.interpretation === "BETWEEN_WITHIN_DIRECTION_DISAGREEMENT" ? "Cycle 组间与组内方向相反，整体相关可能误导。" : ""}{corr.data.data.soc_cycle_decomposition.limitations.length ? ` 限制：${corr.data.data.soc_cycle_decomposition.limitations.join("；")}` : ""}</li>}
            {corr.data.data.alignment_assessment && <li data-testid="report-alignment-assessment">声电时间基准：{corr.data.data.alignment_assessment.status}；关联范围 {corr.data.data.alignment_assessment.association_scope}；确认性推断 {corr.data.data.alignment_assessment.confirmatory_inference_allowed ? "允许" : "不允许"}。{corr.data.data.alignment_assessment.limitation}</li>}
            {!!corr.data.data.soc_by_battery_condition?.length && <li><details data-testid="report-condition-slices"><summary>按 Battery / 充放电阶段展开关系与样本支持</summary><ul className="mt-2 space-y-1">{corr.data.data.soc_by_battery_condition.map((item) => <li key={`${item.battery_id}:${item.state_scope}`}>{item.battery_id} · {electrochemicalPhaseLabel(item.state_scope ?? "unknown")}：r {item.coefficient?.toFixed(3) ?? "不可估计"}，有效配对 {item.n_valid}/{item.n_input}；缺失特征 {item.missing_feature_count}、状态 {item.missing_state_count}、同步排除 {item.excluded_ineligible_count}；{item.status}</li>)}{corr.data.data.soc_by_cycle?.map((item) => <li key={item.scope}>{item.scope}：r {item.coefficient?.toFixed(3) ?? "不可估计"}，有效配对 {item.n_valid}/{item.n_input}；缺失特征 {item.missing_feature_count}、状态 {item.missing_state_count}、同步排除 {item.excluded_ineligible_count}；{item.status}</li>)}</ul><p className="muted text-xs mt-2">此处的 charge/discharge/rest 是电化学阶段切片，不是实验工况切片。各切片均为描述性相关；没有预注册方案前不做多重比较校正或确认性解释。</p></details></li>}
            {corr.data.data.declared_condition_analysis && <li><details data-testid="report-declared-condition-analysis"><summary>按显式申报工况查看 SOC 关系（{corr.data.data.declared_condition_analysis.status}）</summary><p className="muted text-xs mt-2">工况段 {corr.data.data.declared_condition_analysis.segment_count} 个；事件 {corr.data.data.declared_condition_analysis.events_assessed} 个；映射状态：{Object.entries(corr.data.data.declared_condition_analysis.assignment_status_counts).map(([status, count]) => `${status} ${count}`).join("、") || "无"}。</p><ul className="mt-2 space-y-1">{corr.data.data.declared_condition_analysis.results.map((item) => <li key={`${item.condition_axis_id}:${item.condition_value}:${item.unit}:${item.method}:${item.time_reference_asset_ids.join(",")}`}>{item.condition_axis_id} = {item.condition_value}{item.unit ? ` ${item.unit}` : ""} · {item.method} r {item.coefficient?.toFixed(3) ?? "不可估计"} · 有效配对 {item.n_valid_pairs}/{item.n_input_events} · 声明 Battery ID 组 {item.battery_count} / Cycle {item.cycle_count} · {item.status}</li>)}</ul><p className="muted text-xs mt-2">{corr.data.data.declared_condition_analysis.limitations.join(" ")}</p>{corr.data.data.declared_condition_analysis.results.map((item) => <p className="muted text-xs mt-1" key={`${item.condition_axis_id}:${item.condition_value}:${item.method}:limitations`}>{item.condition_axis_id}={item.condition_value}：{item.limitations.join(" ")}</p>)}</details></li>}
            <li data-testid="report-inference-assessment">分析状态：{corr.data.data.inference_assessment.analysis_mode} / {corr.data.data.inference_assessment.claim_scope}；独立单位 {corr.data.data.inference_assessment.independent_unit}；组身份 {corr.data.data.inference_assessment.group_identity_status ?? "NOT_ASSESSED"}；Battery 组数按 {corr.data.data.inference_assessment.group_count_semantics ?? "DECLARED_BATTERY_ID"} 解释；本页包含实时相关系数 {corr.data.data.inference_assessment.correlation_results_included ? "是" : "否"}；置信区间 {corr.data.data.inference_assessment.confidence_interval.status}；p 值 {corr.data.data.inference_assessment.p_value.status}；多重比较 {corr.data.data.inference_assessment.multiple_comparison.status}；混杂调整 {corr.data.data.inference_assessment.confounder_adjustment.status}；研究方案 {corr.data.data.inference_assessment.analysis_plan?.status ?? corr.data.data.inference_assessment.study_protocol_status}；{corr.data.data.inference_assessment.analysis_plan?.study_id ? `Study ${corr.data.data.inference_assessment.analysis_plan.study_id}；` : ""}审批身份核验 {corr.data.data.inference_assessment.analysis_plan?.approval_identity_status ?? "NOT_ASSESSED"} / 审批证据 {corr.data.data.inference_assessment.analysis_plan?.approval_evidence_status ?? "NOT_ASSESSED"}；未解决项 {corr.data.data.inference_assessment.analysis_plan?.unresolved_fields.length ?? "未提供"}；确认性推断 {corr.data.data.inference_assessment.analysis_plan?.confirmatory_inference_enabled ? "已启用" : "未启用"}。{corr.data.data.uncertainty_summary ? ` 不确定性读数：族 ${corr.data.data.uncertainty_summary.family_label}（${corr.data.data.uncertainty_summary.family_size} 项可检验）；已估区间 ${corr.data.data.uncertainty_summary.intervals_estimated} 项、不可估 ${corr.data.data.uncertainty_summary.intervals_not_estimated} 项；方法 ${corr.data.data.uncertainty_summary.interval_method}；多重比较 ${corr.data.data.uncertainty_summary.multiplicity_correction}；仅限探索性。` : ""}</li>
            <li data-testid="report-temperature-correlation"><div>温度关系：{corr.data.data.temperature.status==="TEMPERATURE_UNAVAILABLE"?"本实验无温度通道":corr.data.data.temperature.status}；Pearson r {corr.data.data.temperature.coefficient?.toFixed(3) ?? "不可估计"}，完整配对 {corr.data.data.temperature.n_valid}/{corr.data.data.temperature.n_input}。{corr.data.data.temperature.limitations?.join(" ")}</div><TargetProvenanceAudit target={temperatureTarget} targetId="temperature_c" label="温度" isLoading={targetsQuery.isLoading} error={targetsQuery.error} /></li>
            <li data-testid="report-soh-accounting"><div>SOH：{corr.data.data.soh.status==="NOT_READY_INSUFFICIENT_SOH_STATES"?`仅 ${corr.data.data.soh.distinct_state_count ?? "未知数量"} 个不同 SOH 状态，低于当前分析门槛。`:corr.data.data.soh.status}；有效分析单位为 {corr.data.data.soh.n_valid_unit ?? corr.data.data.soh.independent_unit ?? "未知"}，共 {corr.data.data.soh.n_valid ?? corr.data.data.soh.independent_group_count ?? "未知"} 个有效组；输入/缺失/排除计数以 {corr.data.data.soh.n_input_unit ?? "事件行"} 计，输入 {corr.data.data.soh.n_input ?? "未知"}、特征缺失 {corr.data.data.soh.missing_feature_count ?? "未知"}、状态缺失 {corr.data.data.soh.missing_state_count ?? "未知"}、同步排除 {corr.data.data.soh.excluded_ineligible_count ?? "未知"}。事件帧不作为独立样本。cycle 级摘要 {corr.data.data.soh_cycle_summary.length} 个循环。</div><TargetProvenanceAudit target={sohTarget} targetId="soh_capacity_reference_percent" label="SOH" isLoading={targetsQuery.isLoading} error={targetsQuery.error} /></li>
            <li>无 naive p 值：波形帧存在时间自相关。</li>
          </ul>
        </>}
        {corr.isLoading && <LoadingState/>}{corr.error && <ErrorState error={corr.error} retry={()=>void corr.refetch()}/>}
        </section>;
        })}
      </section>
      <details className="mt-7 border-t pt-3"><summary>证据与可复现性</summary><p className="muted text-sm">证据类别与可用性以科学服务报告为准。</p><Button variant="link" asChild className="px-0"><Link to={`/experiments/${batteryId}/${experimentId}/advanced/evidence`}>查看证据<ArrowRight/></Link></Button><p className="text-xs muted">报告标识：<code>{String(report.report_id)}</code></p>{Array.isArray(report.limitations)&&<p className="text-xs muted mt-2">报告限制：{report.limitations.map(l=>displayName(String(l))).join(" · ")}</p>}</details>
    </article>}{exportError&&<p role="alert" className="notice mt-4">Export failed. Please retry.</p>}
    <Dialog open={confirm} onOpenChange={setConfirm}><DialogContent><DialogHeader><DialogTitle>Generate scientific report</DialogTitle><DialogDescription>Aggregate existing results for {batteryId} / {experimentId}. This request does not refit models. Identical reports may be reused.</DialogDescription></DialogHeader>{create.error&&<p role="alert">Report could not be generated. Retry after checking available artifacts.</p>}<DialogFooter><Button variant="outline" onClick={()=>setConfirm(false)}>Cancel</Button><Button disabled={!canGenerateCurrentReport || create.isPending} onClick={()=>create.mutate()}>Generate report</Button></DialogFooter></DialogContent></Dialog>
  </>;
}
