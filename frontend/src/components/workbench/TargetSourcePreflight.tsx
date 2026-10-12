import { useMutation } from "@tanstack/react-query";
import { CircleCheck, CircleHelp } from "lucide-react";
import {
  client,
  type TargetDefinition,
  type TargetSourceEvidenceRequest,
} from "../../api/client";
import { Button } from "../ui/button";

function buildPreflightRequest(
  batteryId: string,
  experimentId: string,
  target: TargetDefinition | undefined,
  features: string[],
): { request: TargetSourceEvidenceRequest | null; reason: string | null } {
  if (!target?.provenance || !batteryId || !experimentId) {
    return { request: null, reason: "缺少完整的目标来源证据或实验身份，暂时不能核验。" };
  }
  if (!features.length) {
    return { request: null, reason: "先选择至少一个特征，再核验当前 X/y 方案的来源文件。" };
  }
  const targetId = target.target_id === "soc_reference_percent"
    ? "reference_soc_percent"
    : target.target_id;
  if (![
    "reference_soc_percent",
    "temperature_c",
    "soh_capacity_reference_percent",
  ].includes(targetId)) {
    return { request: null, reason: "此目标类型尚无来源预检契约。" };
  }
  const provenance = target.provenance;
  if (!provenance.method_id || !provenance.method_version || !provenance.definition) {
    return { request: null, reason: "目标缺少方法、版本或定义，不能构造可追溯预检请求。" };
  }
  const sourceReferences = provenance.source_assets.map((asset) => ({
    asset_id: asset.asset_id,
    source_reference: asset.source_reference ?? "",
    sha256: asset.sha256,
  }));
  if (!sourceReferences.length || sourceReferences.some((source) =>
    !source.asset_id || !source.source_reference || !/^[a-f\d]{64}$/i.test(source.sha256))) {
    return { request: null, reason: "目标来源缺少 DataAsset 路径或有效 SHA256，不能核验。" };
  }
  const locators = features.map((feature) => {
    const parts = feature.split("@");
    if (parts.length > 2 || !parts[0]?.trim() || (parts.length === 2 && !parts[1]?.trim())) {
      return null;
    }
    return parts.length === 2
      ? { feature_name: parts[0]!.trim(), gate_id: parts[1]!.trim() }
      : { feature_name: feature.trim() };
  });
  if (locators.some((locator) => locator === null)) {
    return { request: null, reason: "所选特征 locator 格式不完整，无法安全核验。" };
  }

  const uncertainty = provenance.uncertainty;
  if (uncertainty.status === "UNKNOWN") {
    if (!uncertainty.reason?.trim()) {
      return { request: null, reason: "未知不确定度必须带有原因，不能省略。" };
    }
  } else if (
    uncertainty.standard_uncertainty == null || !uncertainty.unit?.trim()
    || !uncertainty.method?.trim() || !uncertainty.evidence_refs?.length
  ) {
    return { request: null, reason: "量化不确定度缺少数值、单位、方法或证据引用。" };
  }

  const request: TargetSourceEvidenceRequest = {
    battery_ids: [batteryId],
    experiment_ids: [experimentId],
    target_id: targetId as TargetSourceEvidenceRequest["target_id"],
    target_grain: provenance.target_grain,
    ...(targetId === "soh_capacity_reference_percent" ? { minimum_independent_states: 3 } : {}),
    feature_locators: locators as NonNullable<typeof locators[number]>[],
    label_provenance: {
      semantic_type: target.semantic_type,
      method_id: provenance.method_id,
      method_version: provenance.method_version,
      definition: provenance.definition,
      unit: target.unit,
      independent_unit: provenance.independent_unit,
      source_references: sourceReferences,
      uncertainty: uncertainty.status === "UNKNOWN"
        ? { status: "UNKNOWN", reason: uncertainty.reason! }
        : {
            status: "QUANTIFIED",
            standard_uncertainty: uncertainty.standard_uncertainty!,
            unit: uncertainty.unit!,
            method: uncertainty.method!,
            evidence_refs: uncertainty.evidence_refs!,
          },
    },
  };
  return { request, reason: null };
}

export function TargetSourcePreflight({
  batteryId,
  experimentId,
  target,
  features,
}: {
  batteryId: string;
  experimentId: string;
  target: TargetDefinition | undefined;
  features: string[];
}) {
  const { request, reason } = buildPreflightRequest(batteryId, experimentId, target, features);
  const mutation = useMutation({
    mutationFn: (body: TargetSourceEvidenceRequest) => client.validateTargetSourceEvidence(body),
  });
  const isCurrentSubmission = Boolean(
    request && mutation.variables && JSON.stringify(request) === JSON.stringify(mutation.variables),
  );
  const result = isCurrentSubmission ? mutation.data?.data : undefined;

  return <section className="notice mt-4" aria-labelledby="target-source-preflight-title" data-testid="target-source-preflight">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 id="target-source-preflight-title" className="font-medium">目标来源文件完整性预检</h3>
        <p className="text-xs mt-1">校验 DataAsset 身份、raw 文件 SHA256，以及对应 Parser 输出完整性；不验证标签科学语义/target readiness，也不创建或修改数据集。</p>
      </div>
      <Button
        type="button"
        variant="outline"
        disabled={!request || mutation.isPending}
        onClick={() => request && mutation.mutate(request)}
      >
        {mutation.isPending ? "核验中…" : "核验目标来源文件"}
      </Button>
    </div>
    {reason && <p className="text-xs mt-2" role="status">{reason}</p>}
    {mutation.isError && isCurrentSubmission && <p className="text-sm mt-2" role="alert">来源或 Parser 产物未能通过完整性预检；请检查 DataAsset manifest、原始文件与解析产物后重试。原有目标状态不会改变。</p>}
    {result && <div className="grid gap-1 mt-3 text-xs" role="status" data-testid="target-source-preflight-result">
      <p data-testid="target-source-integrity-status"><CircleCheck size={13} className="inline mr-1 text-emerald-700" />文件完整性已核验：{result.verified_sources.length} 个来源，SHA256 与当前 raw 文件匹配。</p>
      <p data-testid="target-source-semantics-status"><CircleHelp size={13} className="inline mr-1" />标签语义与 target readiness：未评估（仍以目标卡片原状态为准）。</p>
      <p>Parser provenance：{result.verified_sources.map((source) => `${source.asset_id} ${source.parser_provenance}`).join(" · ")}</p>
      <p data-testid="target-source-materialization-status">未创建数据集；物化开关保持关闭。</p>
    </div>}
  </section>;
}
