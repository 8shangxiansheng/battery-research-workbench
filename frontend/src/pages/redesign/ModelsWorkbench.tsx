import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { getCoreRowModel, getSortedRowModel, useReactTable, flexRender, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { client, type ResultRecord, type SourceDatasetRecord } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from "../../components/ui/table";
import { PageHeader, LoadingState, ErrorState, EmptyState, ScopeNote } from "../../components/workbench/shared";
import { SelectedFeaturesPanel } from "../../components/workbench/SelectedFeaturesPanel";
import { displayName, modelComparison, numberText } from "../../lib/presentation";
import { StaleBanner } from "./WorkbenchShell";
import { useWorkflowContext } from "../../hooks/useWorkflowContext";
import { partitionResultsByDataset } from "../../lib/result-freshness";

function ComparisonTable({rows}:{rows:ResultRecord[]}) {
  const [sorting,setSorting]=useState<SortingState>([]);
  const columns=useMemo<ColumnDef<ResultRecord>[]>(()=>[
    {accessorKey:"strategy",header:"模型",cell:ctx=><span className="font-medium">{displayName(String(ctx.getValue()))}{ctx.getValue()==="DUMMY_MEAN" && <Badge variant="secondary" className="ml-3">参考基线</Badge>}</span>},
    {accessorKey:"value",header:"宏观 MAE（%）",cell:ctx=><span className="tabular-nums">{numberText(ctx.getValue())}</span>},
    {accessorKey:"scientific_status",header:"范围",cell:()=>"有限评估"},
  ],[]);
  const table=useReactTable({data:rows,columns,state:{sorting},onSortingChange:setSorting,getCoreRowModel:getCoreRowModel(),getSortedRowModel:getSortedRowModel()});
  return <Table><TableHeader>{table.getHeaderGroups().map(g=><TableRow key={g.id}>{g.headers.map(h=><TableHead key={h.id}><button onClick={h.column.getToggleSortingHandler()} aria-label={`按 ${h.column.id} 排序`}>{flexRender(h.column.columnDef.header,h.getContext())}</button></TableHead>)}</TableRow>)}</TableHeader><TableBody>{table.getRowModel().rows.map(r=><TableRow key={r.id} className={r.original.strategy==="DUMMY_MEAN"?"bg-[#f1f5f4]":""}>{r.getVisibleCells().map(c=><TableCell key={c.id}>{flexRender(c.column.columnDef.cell,c.getContext())}</TableCell>)}</TableRow>)}</TableBody></Table>;
}

export function modelingRunRequest(
  batteryId: string,
  experimentId: string,
  selectedFeatures: string[],
) {
  return {
    profile: "FULL_PRE_MODEL",
    battery_id: batteryId,
    experiment_id: experimentId,
    stages: ["DATASET", "SPLIT", "FEATURE_ANALYSIS", "SOC_MODELING", "SCIENTIFIC_REPORT"],
    target: "soc_reference_percent",
    features: { selected_features: selectedFeatures },
    fold_index: 1,
    split: {
      strategy: "LEAVE_ONE_GROUP_OUT",
      split_unit: "CYCLE",
      group_column: "cycle_group_id",
    },
    feature_analysis: {
      analysis_mode: "TRAIN_ONLY_ML_SAFE",
      target: "soc_reference_percent",
      candidate_features: selectedFeatures,
      fold_index: 1,
      methods: ["descriptive", "spearman"],
      selection: {
        requested: true,
        mode: "TRAIN_ONLY_RULE_BASED",
        policy: { min_abs_spearman: 0.15, max_missing_fraction: 0.05 },
      },
    },
    modeling: { strategies: FIXED_BASELINE_SUITE, random_state: 42 },
  };
}

function CohortLOBOPanel({ batteryId, experimentId }: { batteryId: string; experimentId: string }) {
  const qc = useQueryClient();
  const cohorts = useQuery({
    queryKey: ["cohort-datasets"],
    queryFn: () => client.listCohortDatasets(),
  });
  const eligible = (cohorts.data?.data ?? []).find((item) =>
    item.status === "READY_FOR_BATTERY_SPLIT" && item.battery_count >= 2 &&
    item.source_datasets.some((source) => source.battery_id === batteryId && source.experiment_id === experimentId),
  );
  const evaluate = useMutation({
    mutationFn: () => client.runCohortLOBO(eligible!.cohort_dataset_id),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["cohort-datasets"] }); },
  });
  const result = evaluate.data?.data;
  return <section className="panel !p-5 mt-6" data-testid="cohort-lobo-panel">
    <h3 className="text-base font-medium">跨电池验证 / Battery-level LOBO</h3>
    <p className="text-sm muted mt-1">独立队列入口。只使用通过来源、标签与特征映射校验的 harmonized cohort；Dummy/固定基线，不做调参。</p>
    {cohorts.isLoading && <p className="text-sm mt-3" role="status">正在检查可用队列…</p>}
    {cohorts.error && <p className="text-sm mt-3 text-[#9b782e]" role="alert">队列状态暂时无法读取。<button className="underline ml-1" onClick={() => void cohorts.refetch()}>重试</button></p>}
    {!cohorts.isLoading && !cohorts.error && !eligible && <p className="notice text-sm mt-3" data-testid="cohort-lobo-blocked">
      尚无包含当前实验且至少有 2 块独立电池的已验证队列；跨电池泛化仍为阻断状态。登记电池数或 CELL_001 自身循环数不构成该证据。
    </p>}
    {eligible && <div className="mt-3 flex items-center gap-3 flex-wrap">
      <Badge variant="secondary">队列就绪 · {eligible.battery_count} 块电池 · {eligible.row_count} 条事件</Badge>
      <Button size="sm" data-testid="run-cohort-lobo" disabled={evaluate.isPending}
        onClick={() => evaluate.mutate()}>{evaluate.isPending ? "LOBO 评估中…" : "运行固定基线 LOBO"}</Button>
      {evaluate.error && <span className="text-sm text-[#9b782e]" role="alert">评估未完成：{(evaluate.error as Error).message}</span>}
    </div>}
    {result && <div className="mt-4" data-testid="cohort-lobo-result">
      <p className="text-sm font-medium">LOBO 有限评估 · {result.battery_count} 块留出电池 · 等权宏观 MAE（%）</p>
      <div className="flex flex-wrap gap-3 mt-2">{Object.entries(result.macro_by_strategy).map(([strategy, metrics]) =>
        <span className="badge" key={strategy}>{displayName(strategy)}：{numberText(metrics.macro_MAE)}</span>)}
      </div>
      <div className="panel !p-0 overflow-hidden mt-4"><Table><TableHeader><TableRow>
        <TableHead>模型</TableHead><TableHead>留出电池</TableHead><TableHead>Fold</TableHead><TableHead>事件行数</TableHead><TableHead>MAE（%）</TableHead>
      </TableRow></TableHeader><TableBody>{result.battery_results.map((row) => <TableRow key={`${row.strategy}-${row.battery_id}`}>
        <TableCell>{displayName(row.strategy)}</TableCell><TableCell>{row.battery_id}</TableCell><TableCell>{row.fold}</TableCell><TableCell>{row.row_count}</TableCell><TableCell>{numberText(row.overall.MAE)}</TableCell>
      </TableRow>)}</TableBody></Table></div>
      <p className="text-xs muted mt-2">Pooled-row diagnostic MAE：{numberText(result.pooled_row_diagnostic_by_strategy.DUMMY_MEAN?.MAE)}。池化行仅作诊断，不替代按电池等权结果；合成验证不代表真实跨电池泛化。</p>
      {result.provenance && <details className="mt-3 text-xs muted"><summary>来源与 harmonization provenance</summary>
        <p className="mt-2">Policy：{result.provenance.harmonization_policy_id} · 方法：{result.provenance.harmonization_method_version}</p>
        <ul>{result.provenance.source_datasets.map((source) => <li key={source.source_dataset_id}>{source.battery_id} / {source.experiment_id}</li>)}</ul>
      </details>}
    </div>}
  </section>;
}

function CohortBuilderPanel() {
  const qc = useQueryClient();
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: () => client.listDatasets() });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [featureIds, setFeatureIds] = useState<string[]>([]);
  const [cohortId, setCohortId] = useState("");
  const [policyId, setPolicyId] = useState("");
  const [evidenceText, setEvidenceText] = useState("");
  const sources = datasets.data?.data ?? [];
  const selected = selectedIds.map((id) => sources.find((source) => source.dataset_id === id)).filter((source): source is SourceDatasetRecord => !!source);
  const sameLabelMethod = selected.length >= 2 && new Set(selected.map((source) => source.target_method_version)).size === 1
    && new Set(selected.map((source) => source.soc_label_temporality)).size === 1;
  const features = useMemo(() => {
    if (selected.length < 2) return [];
    const first = selected[0]!;
    return first.feature_definitions.filter((definition) =>
      first.predictor_columns.includes(definition.name) && definition.unit && definition.version &&
      selected.every((source) => source.predictor_columns.includes(definition.name) &&
        source.feature_definitions.some((item) => item.name === definition.name && item.unit === definition.unit &&
          item.version === definition.version && item.definition_signature === definition.definition_signature)),
    );
  }, [selected]);
  const defaultCohortId = `COHORT::${selected.map((item) => item.battery_id.replace(/[^A-Za-z0-9_-]/g, "-")).sort().join("-")}`;
  const evidenceRefs = evidenceText.split(",").map((value) => value.trim()).filter(Boolean);
  const create = useMutation({
    mutationFn: () => {
      const sourceTargetIds = Object.fromEntries(selected.map((source) => [source.dataset_id, source.target_column]));
      const featureMappings = featureIds.map((featureId) => ({
        canonical_feature_id: featureId,
        source_feature_ids: Object.fromEntries(selected.map((source) => [source.dataset_id, featureId])),
        method_version: features.find((feature) => feature.name === featureId)!.version,
      }));
      const unitMapping = Object.fromEntries(featureIds.map((featureId) => {
        const definition = features.find((feature) => feature.name === featureId)!;
        return [featureId, {
          source_units: Object.fromEntries(selected.map((source) => [source.dataset_id, definition.unit])),
          canonical_unit: definition.unit,
        }];
      }));
      return client.createCohortDataset({
        cohort_id: cohortId.trim() || defaultCohortId,
        source_datasets: selected.map(({ dataset_id, battery_id, experiment_id }) => ({
          source_dataset_id: dataset_id, battery_id, experiment_id,
        })),
        target_mapping: {
          canonical_target_id: "reference_soc_percent",
          source_target_ids: sourceTargetIds,
          unit: "percent",
          method_version: selected[0]!.target_method_version,
        },
        feature_mappings: featureMappings,
        unit_mapping: unitMapping,
        harmonization_method_version: "exact-definition-match/1.0",
        harmonization_policy_id: policyId.trim(),
        evidence_refs: evidenceRefs,
        group_column: "battery_id",
      });
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["cohort-datasets"] }); },
  });
  const validSources = sources.filter((source) => source.dataset_family === "SOC" &&
    ["READY_FOR_SPLIT", "READY_WITH_LIMITATIONS"].includes(source.dataset_status) &&
    source.target_column === "soc_reference_percent" && source.target_method_version && source.soc_label_temporality);
  const uniqueBatteries = new Set(selected.map((source) => source.battery_id)).size === selected.length;
  const canCreate = selected.length >= 2 && uniqueBatteries && sameLabelMethod && featureIds.length > 0 &&
    !!policyId.trim() && evidenceRefs.length > 0 && !!(cohortId.trim() || defaultCohortId);
  const toggleSource = (source: SourceDatasetRecord) => {
    setSelectedIds((prior) => prior.includes(source.dataset_id)
      ? prior.filter((id) => id !== source.dataset_id)
      : [...prior, source.dataset_id]);
    setFeatureIds([]);
    create.reset();
  };
  const toggleFeature = (featureId: string) => setFeatureIds((prior) =>
    prior.includes(featureId) ? prior.filter((item) => item !== featureId) : [...prior, featureId],
  );

  return <section className="panel !p-5 mt-6" data-testid="cohort-builder-panel">
    <h3 className="text-base font-medium">建立跨电池队列 / Build harmonized cohort</h3>
    <p className="text-sm muted mt-1">选择已有、manifest-backed SOC datasets。这里仅提交明示的身份/定义映射；单位不转换，服务端会再次验证来源与 checksum。</p>
    {datasets.isLoading && <p className="text-sm mt-3" role="status">正在检查 SOC 数据集…</p>}
    {datasets.error && <p className="text-sm mt-3 text-[#9b782e]" role="alert">数据集目录读取失败。<button className="underline ml-1" onClick={() => void datasets.refetch()}>重试</button></p>}
    {!datasets.isLoading && !datasets.error && validSources.length === 0 && <p className="notice text-sm mt-3" data-testid="cohort-builder-empty">
      暂无可用于队列构建的 SOC 数据集；先完成各电池的数据集构建。注册电池或合成测试不会变成真实验证证据。
    </p>}
    {validSources.length > 0 && <>
      <fieldset className="mt-4">
        <legend className="text-sm font-medium">选择至少 2 块不同电池的 source datasets</legend>
        <div className="grid gap-2 mt-2 md:grid-cols-2">{validSources.map((source) => <label key={source.dataset_id} className="flex items-start gap-2 rounded-md border p-3 text-sm">
          <input type="checkbox" data-testid={`cohort-source-${source.battery_id}`} checked={selectedIds.includes(source.dataset_id)} onChange={() => toggleSource(source)} />
          <span><strong>{source.battery_id}</strong> · {source.experiment_id}<span className="block muted">SOC · {source.eligible_rows} rows · {source.predictor_columns.length} predictors</span></span>
        </label>)}</div>
      </fieldset>
      {selected.length >= 2 && <>
        {!uniqueBatteries && <p className="text-sm text-[#9b782e] mt-3" role="alert">每个外层 LOBO fold 必须代表一块独立电池；请移除重复 battery。</p>}
        {!sameLabelMethod && <p className="text-sm text-[#9b782e] mt-3" role="alert">所选 source 的 SOC 公式版本或标签时间语义不同，不能合并。</p>}
        <fieldset className="mt-4">
          <legend className="text-sm font-medium">精确定义一致的候选特征</legend>
          <div className="flex flex-wrap gap-3 mt-2">{features.map((feature) => <label key={feature.name} className="inline-flex items-center gap-2 text-sm">
            <input type="checkbox" data-testid={`cohort-feature-${feature.name}`} checked={featureIds.includes(feature.name)} onChange={() => toggleFeature(feature.name)} />
            {feature.name} <span className="muted">{feature.unit} · v{feature.version}</span>
          </label>)}</div>
          {features.length === 0 && <p className="text-sm muted mt-2">所选数据集没有可验证的共同 predictor definitions。</p>}
        </fieldset>
        <details className="mt-4"><summary>队列策略与证据引用（必填）</summary>
          <label className="block text-sm mt-3">Cohort label
            <input className="input mt-1 w-full" value={cohortId || defaultCohortId} onChange={(event) => setCohortId(event.target.value)} />
          </label>
          <label className="block text-sm mt-3">Harmonization policy ID
            <input className="input mt-1 w-full" value={policyId} onChange={(event) => setPolicyId(event.target.value)} placeholder="例如 POLICY::soc-reference-v1" />
          </label>
          <label className="block text-sm mt-3">Evidence references（逗号分隔）
            <input className="input mt-1 w-full" value={evidenceText} onChange={(event) => setEvidenceText(event.target.value)} placeholder="记录 SOP / 定义评审 / 实验依据" />
          </label>
        </details>
        <Button className="mt-4" data-testid="create-cohort" disabled={!canCreate || create.isPending}
          onClick={() => create.mutate()}>{create.isPending ? "验证并生成中…" : "验证映射并生成不可变 cohort"}</Button>
        {create.error && <p className="text-sm text-[#9b782e] mt-2" role="alert">队列未创建：{(create.error as Error).message}</p>}
        {create.data && <p className="notice text-sm mt-3" role="status" data-testid="cohort-created">
          队列已验证 · {create.data.data.battery_count} 块电池 · {create.data.data.row_count} 条事件。来源变更后需要新版本；可在下方启动固定基线 LOBO。
        </p>}
      </>}
    </>}
  </section>;
}
/**
 * Dataset → modeling handoff (official orchestrator path only):
 * shows the prerequisite chain, creates the grouped split when missing,
 * offers a read-only dry-run plan and a FULL_PRE_MODEL run start. Run
 * progress and user actions (CONFIRM_FEATURE_SELECTION etc.) are handled
 * on the Runs page — this panel never trains or rebuilds implicitly.
 */
/** The predeclared fixed baseline suite (mirrors modeling/schemas.STRATEGIES
 *  order; Dummy stays first — no tuning, no additions at runtime). */
const FIXED_BASELINE_SUITE = [
  "DUMMY_MEAN", "LINEAR_REGRESSION", "RIDGE",
  "SUPPORT_VECTOR_REGRESSION", "GAUSSIAN_PROCESS_REGRESSION", "K_NEAREST_NEIGHBORS",
  "RANDOM_FOREST", "GRADIENT_BOOSTING",
];

function ModelingLauncher({ batteryId, experimentId, wf }: { batteryId: string; experimentId: string; wf: ReturnType<typeof useWorkflowContext>["data"] }) {
  const qc = useQueryClient();
  const splitsQ = useQuery({ queryKey: ["splits", batteryId, experimentId], queryFn: () => client.listSplits(batteryId, experimentId) });
  const runsQ = useQuery({ queryKey: ["runs", 5], queryFn: () => client.listRuns(5) });
  const steps = wf?.steps ?? {};
  const datasetId = (steps.DATASET?.committed as { dataset_id?: string } | undefined)?.dataset_id
    ?? (steps.SPLIT?.committed as { dataset_id?: string } | undefined)?.dataset_id ?? null;
  const hasSplit = !!(steps.SPLIT?.committed as { split_id?: string } | undefined)?.split_id
    || (splitsQ.data?.data.splits ?? []).length > 0;
  const waitingRun = (runsQ.data?.data.runs ?? []).find(r => r.status === "WAITING_FOR_USER" && r.experiment_id === experimentId);
  const createSplit = useMutation({
    mutationFn: () => client.createSplit({ battery_id: batteryId, experiment_id: experimentId, dataset_id: datasetId! }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["splits", batteryId, experimentId] }); },
  });
  const selectedFeatures = ((steps.DATASET?.committed as { selected_features?: string[] } | undefined)?.selected_features ?? []);
  const request = modelingRunRequest(batteryId, experimentId, selectedFeatures);
  const dryRun = useMutation({ mutationFn: () => client.dryRun(request) });
  const startRun = useMutation({
    mutationFn: () => client.startRun(request),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["runs", 5] }); },
  });
  const planned = (dryRun.data?.data as { nodes?: { node_id: string; state: string }[] } | undefined)?.nodes ?? [];
  return <section className="panel !p-5 mt-6" data-testid="modeling-launcher">
    <h3 className="text-base font-medium">建模流程接入 / Modeling handoff</h3>
    <p className="text-sm muted mt-1">链路：数据集 → 分组划分 → 训练运行（官方编排器 FULL_PRE_MODEL）。特征锁定确认在运行页以“用户动作”完成，系统不会自动重建或自动训练。</p>
    <p className="text-sm mt-3" data-testid="launcher-chain">
      数据集: <strong>{datasetId ? "已就绪" : "未构建"}</strong> · 分组划分: <strong>{hasSplit ? "已就绪" : "缺失"}</strong>
    </p>
    {!datasetId && <p className="text-sm mt-2">先到 <Link className="underline" to={`/experiments/${batteryId}/${experimentId}/analysis?step=dataset`}>特征分析 → 数据集</Link> 构建数据集。</p>}
    {datasetId && !hasSplit && <p className="mt-2"><Button variant="outline" size="sm" data-testid="launcher-create-split" disabled={createSplit.isPending}
      onClick={() => createSplit.mutate()}>{createSplit.isPending ? "创建中…" : "创建分组划分 / Create grouped split"}</Button></p>}
    {waitingRun && <p className="notice text-sm mt-2" role="status" data-testid="launcher-waiting-run">
      有一个运行正在等待你的确认（特征选择/参数）：<Link className="underline" to="/runs">前往运行页处理</Link></p>}
    <div className="flex gap-3 mt-3 items-center flex-wrap">
      <Button variant="outline" size="sm" data-testid="launcher-dry-run" disabled={!datasetId || !hasSplit || dryRun.isPending}
        onClick={() => dryRun.mutate()}>{dryRun.isPending ? "计划中…" : "查看运行计划（只读 dry-run）"}</Button>
      <Button size="sm" data-testid="launcher-start-run" disabled={!datasetId || !hasSplit || !selectedFeatures.length || !!waitingRun || startRun.isPending}
        onClick={() => startRun.mutate()}>{startRun.isPending ? "启动中…" : "启动建模运行 / Start run"}</Button>
      {startRun.isSuccess && <span className="text-sm">已启动：<code>{String((startRun.data as { data?: { run_id?: string } })?.data?.run_id ?? "").slice(0, 28)}</code> · <Link className="underline" to="/runs">运行页跟踪与确认</Link></span>}
      {startRun.error && <span className="text-sm text-[#9b782e]" data-testid="launcher-start-error">启动失败：{(startRun.error as Error).message?.slice(0, 120)}</span>}
    </div>
    {planned.length > 0 && <ul className="text-xs muted mt-3 grid grid-cols-2 gap-x-6 gap-y-1" data-testid="launcher-plan">
      {planned.map(n => <li key={n.node_id}>{n.node_id} — {n.state}</li>)}
    </ul>}
  </section>;
}

export function ModelsWorkbench() {
  const {batteryId="",experimentId=""}=useParams();
  const wf = useWorkflowContext(batteryId, experimentId);
  const results=useQuery({queryKey:["results",batteryId,experimentId],queryFn:()=>client.getResults(batteryId,experimentId)});
  if(results.isLoading || wf.isLoading)return <LoadingState/>;
  if(results.error)return <ErrorState error={results.error} retry={()=>void results.refetch()}/>;
  if(wf.error && !wf.data)return <ErrorState error={wf.error} retry={()=>void wf.refetch()}/>;
  const committed = wf.data?.steps.DATASET?.committed as { dataset_id?: string } | undefined;
  const currentDatasetId = committed?.dataset_id ?? null;
  const partition = partitionResultsByDataset(results.data?.data ?? [], currentDatasetId);
  const rows=partition.current;const {macro,dummy,beats}=modelComparison(rows);
  const historicalComparison=modelComparison(partition.historical).macro;
  const datasetIds=[...new Set(rows.map(r=>r.dataset_id).filter((d): d is string => !!d))];
  return <><PageHeader eyebrow="先看证据，再谈性能" title="SOC 建模" description="有没有模型跑赢简单基线？" actions={<Button variant="outline" asChild><Link to={`/experiments/${batteryId}/${experimentId}/report`}>Open report<ArrowRight/></Link></Button>}/>
    {wf.data && <StaleBanner freshness={wf.data.artifact_freshness} stepKey="MODELS" />}
    <ModelingLauncher batteryId={batteryId} experimentId={experimentId} wf={wf.data} />
    <CohortBuilderPanel />
    <CohortLOBOPanel batteryId={batteryId} experimentId={experimentId} />
    {!macro.length ? <EmptyState title="当前数据集尚无模型评估" to={`/experiments/${batteryId}/${experimentId}/analysis?step=selection`} action="复核分组划分与特征选择">
      当前数据集 <code>{currentDatasetId ?? "尚未提交"}</code> 没有匹配的模型结果。历史结果不会被用于当前结论；先确认 grouped split，再启动固定基线运行。
    </EmptyState> : <>
      <Badge variant="secondary">评估完成 · 有限范围</Badge><div className="finding"><h2>{beats===false?"当前没有任何模型跑赢 Dummy 基准。":beats===true?"有模型在本次评估中跑赢了 Dummy。":"暂无可比的 Dummy 基线。"}</h2><p className="muted mt-4 max-w-2xl">{beats===false?"当前特征尚未展现出预测优势。这是科学结论，不是处理故障。":"该对比不能证明跨电池泛化或生产可用性。"}</p></div>
      {dummy && <p className="mb-7 text-sm"><span className="muted">Dummy 均值 · 宏观 MAE</span><strong className="text-2xl ml-4 tabular-nums">{numberText(dummy.value)}<span className="text-sm muted ml-1">%</span></strong></p>}
      <section className="panel !p-0 overflow-hidden" data-testid="model-comparison-current"><div className="p-5 border-b"><h3>Model comparison · current dataset</h3><p className="text-xs muted mt-1">Lower MAE is better. Values are reported by the scientific service.</p></div><ComparisonTable rows={macro}/></section>
      <SelectedFeaturesPanel datasetId={datasetIds[0]} />
      <details className="mt-5"><summary>Advanced evaluation details</summary><Table><TableHeader><TableRow><TableHead>模型</TableHead><TableHead>指标</TableHead><TableHead>折</TableHead><TableHead>数值</TableHead><TableHead>证据</TableHead></TableRow></TableHeader><TableBody>{rows.filter(r=>r.result_type==="MODEL_METRIC").map(r=><TableRow key={r.result_id}><TableCell>{displayName(r.strategy??"")}</TableCell><TableCell>{r.name}</TableCell><TableCell>{r.fold_index??"—"}</TableCell><TableCell>{numberText(r.value)} {r.units}</TableCell><TableCell>{displayName(r.evidence_type)}</TableCell></TableRow>)}</TableBody></Table><p className="muted text-sm mt-3">OOB 与方向性指标仅在后端提供时显示。此处不计算池化行指标。</p></details>
    </>}
    {partition.historical.length > 0 && <section className="panel !p-5 mt-6" data-testid="historical-model-results" role="status">
      <div className="flex items-center gap-2"><Badge variant="outline">历史 / Stale</Badge><h3>旧数据集模型结果</h3></div>
      <p className="text-sm muted mt-2">这些结果来自非当前数据集，不能支撑当前模型结论或新报告。重新构建对应 split 与模型后，结果会按 dataset ID 自动归入当前评估。</p>
      <p className="text-xs font-mono mt-2">旧 dataset IDs：{[...new Set(partition.historical.map(row => row.dataset_id ?? "unscoped"))].join(" · ")}</p>
      {historicalComparison.length > 0 && <details className="mt-3"><summary>查看历史指标（不参与当前结论）</summary><div className="mt-3"><ComparisonTable rows={historicalComparison}/></div></details>}
    </section>}
    <ScopeNote/></>;
}
