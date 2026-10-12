import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { client, type ExperimentDataAsset, type TimebaseValidationRecord } from "../../api/client";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "../ui/dialog";
import { Input } from "../ui/input";

type AnchorDraft = {
  absoluteStartTime: string;
  sourceReference: string;
  sourceSha256: string;
  error: string;
  ambiguityFree: boolean;
};

const splitRefs = (value: string) => value.split("\n").map(item => item.trim()).filter(Boolean);
const unusableEvidenceStatuses = new Set(["STALE_EVIDENCE", "INVALID_RECORD", "NOT_VERIFIED"]);

function evidenceIntegrityMessage(status: string | undefined): string | null {
  if (status === "STALE_EVIDENCE") {
    return "审核证据文件与记录的 SHA-256 不一致或已不可用。请提交新提案并重新审核；旧提案不能用于重算。";
  }
  if (status === "INVALID_RECORD") {
    return "审核证据审计记录格式无效或内部不一致。请勿应用该锚点；核查审计记录，必要时撤销并重新提交。";
  }
  if (status === "NOT_VERIFIED") {
    return "提案或审核证据缺少可验证的文件 checksum。该记录不能用于重算；请补齐并重新提交审核证据。";
  }
  return null;
}

export function TimebaseValidationPanel({ batteryId, experimentId }: {
  batteryId: string;
  experimentId: string;
}) {
  const [open, setOpen] = useState(false);
  const [record, setRecord] = useState<TimebaseValidationRecord | null>(null);
  const [timezone, setTimezone] = useState("");
  const [tolerance, setTolerance] = useState("1");
  const [submissionEvidence, setSubmissionEvidence] = useState("");
  const [reviewEvidence, setReviewEvidence] = useState("");
  const [operator, setOperator] = useState("");
  const [rationale, setRationale] = useState("");
  const [loadingRecordId, setLoadingRecordId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [recomputeRun, setRecomputeRun] = useState<Record<string, unknown> | null>(null);
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, AnchorDraft>>({});
  const assetsQuery = useQuery({
    queryKey: ["experiment-assets", batteryId, experimentId],
    queryFn: () => client.listExperimentAssets(batteryId, experimentId),
    enabled: open,
  });
  const validationsQuery = useQuery({
    queryKey: ["timebase-validations", batteryId, experimentId],
    queryFn: () => client.listTimebaseValidations(batteryId, experimentId),
    enabled: open,
  });
  const assets = assetsQuery.data?.data.assets ?? [];
  const initializedDrafts = useMemo(() => {
    const next = { ...drafts };
    for (const asset of assets) {
      if (!next[asset.asset_id]) {
        next[asset.asset_id] = {
          absoluteStartTime: "",
          sourceReference: "",
          sourceSha256: "",
          error: "",
          ambiguityFree: false,
        };
      }
    }
    return next;
  }, [assets, drafts]);
  const preflightRefs = [...new Set([
    ...splitRefs(submissionEvidence),
    ...assets.map(asset => initializedDrafts[asset.asset_id]?.sourceReference.trim() ?? "").filter(Boolean),
  ])];
  const preflight = useMutation({
    mutationFn: (references: string[]) => client.preflightTimebaseEvidence(
      batteryId, experimentId, references,
    ),
    onSuccess: (result, references) => {
      const verified = result.data.verified_evidence;
      setDrafts(current => {
        const next = { ...current };
        for (const asset of assets) {
          const draft = next[asset.asset_id] ?? initializedDrafts[asset.asset_id];
          const entry = draft?.sourceReference.trim()
            ? verified[draft.sourceReference.trim()]
            : undefined;
          if (draft && entry) next[asset.asset_id] = { ...draft, sourceSha256: entry.sha256 };
        }
        return next;
      });
      setSubmissionEvidence(references.join("\n"));
    },
  });
  const preflightIsCurrent = Boolean(
    preflight.data && JSON.stringify(preflight.variables) === JSON.stringify(preflightRefs),
  );
  const submit = useMutation({
    mutationFn: () => client.submitTimebaseValidation(batteryId, experimentId, {
      contract_version: "timebase-validation/1.1",
      battery_id: batteryId,
      experiment_id: experimentId,
      timezone: timezone.trim(),
      anchors: assets.map(asset => ({
        asset_id: asset.asset_id,
        absolute_start_time: initializedDrafts[asset.asset_id]?.absoluteStartTime.trim() ?? "",
        source_reference: initializedDrafts[asset.asset_id]?.sourceReference.trim() ?? "",
        source_sha256: initializedDrafts[asset.asset_id]?.sourceSha256.trim() ?? "",
      })),
      evidence_refs: splitRefs(submissionEvidence),
      maximum_allowed_error_s: Number(tolerance),
    }),
    onSuccess: async result => {
      setRecord(result.data);
      await queryClient.invalidateQueries({ queryKey: ["timebase-validations", batteryId, experimentId] });
    },
  });
  const review = useMutation({
    mutationFn: (decision: "ACCEPT" | "REJECT" | "REVOKE") => client.reviewTimebaseValidation(
      batteryId,
      experimentId,
      record!.validation_id,
      {
        decision,
        operator_identity: operator.trim(),
        rationale: rationale.trim(),
        evidence_refs: decision === "ACCEPT" ? splitRefs(reviewEvidence) : [],
        error_by_asset_s: decision === "ACCEPT"
          ? Object.fromEntries(assets.map(asset => [asset.asset_id, Number(initializedDrafts[asset.asset_id]?.error)]))
          : {},
        ambiguity_free_assets: decision === "ACCEPT"
          ? assets.filter(asset => initializedDrafts[asset.asset_id]?.ambiguityFree).map(asset => asset.asset_id)
          : [],
      },
    ),
    onSuccess: async result => {
      setRecord(current => current ? {
        ...current,
        ...result.data,
        events: [...(current.events ?? []), ...(result.data.event ? [result.data.event] : [])],
      } : result.data);
      await queryClient.invalidateQueries({ queryKey: ["timebase-validations", batteryId, experimentId] });
    },
  });
  const recompute = useMutation({
    mutationFn: () => client.startRun({
      profile: "INGEST_TO_MEASUREMENT_EVENTS",
      battery_id: batteryId,
      experiment_id: experimentId,
      parameters: record?.status === "REVOKED_PENDING_RECOMPUTE"
        ? {}
        : { timebase_validation_id: record?.validation_id },
    }),
    onSuccess: async result => {
      setRecomputeRun(result.data);
      await queryClient.invalidateQueries({ queryKey: ["synchronization", batteryId, experimentId] });
      await queryClient.invalidateQueries({ queryKey: ["alignment-summary", batteryId, experimentId] });
      if (record) {
        const refreshed = await client.getTimebaseValidation(batteryId, experimentId, record.validation_id);
        setRecord(refreshed.data);
      }
    },
  });

  const patchDraft = (assetId: string, patch: Partial<AnchorDraft>) => {
    const currentDraft = initializedDrafts[assetId];
    if (!currentDraft) return;
    setDrafts(current => {
      const nextDraft = { ...currentDraft, ...patch };
      if (patch.sourceReference !== undefined
        && patch.sourceReference.trim() !== currentDraft.sourceReference.trim()) {
        nextDraft.sourceSha256 = "";
      }
      return { ...current, [assetId]: nextDraft };
    });
  };
  const canSubmit = assets.length > 0
    && Boolean(timezone.trim())
    && Number.isFinite(Number(tolerance))
    && Number(tolerance) > 0
    && Boolean(splitRefs(submissionEvidence).length)
    && assets.every(asset => {
      const draft = initializedDrafts[asset.asset_id];
      return Boolean(draft?.absoluteStartTime.trim() && draft.sourceReference.trim() && /^[a-fA-F0-9]{64}$/.test(draft.sourceSha256.trim()));
    });
  const canAccept = assets.length > 0
    && Boolean(operator.trim() && rationale.trim() && splitRefs(reviewEvidence).length)
    && assets.every(asset => {
      const draft = initializedDrafts[asset.asset_id];
      return draft?.error.trim() !== "" && Number.isFinite(Number(draft?.error)) && draft?.ambiguityFree;
    });
  const evidenceBlocked = unusableEvidenceStatuses.has(record?.evidence_integrity_status ?? "");
  const recomputeBlocked = evidenceBlocked && record?.status !== "REVOKED_PENDING_RECOMPUTE";

  return <Dialog open={open} onOpenChange={next => {
    setOpen(next);
    if (!next) {
      setRecord(null);
      setRecomputeRun(null);
      submit.reset();
      review.reset();
    }
  }}>
    <DialogTrigger asChild><Button variant="outline" size="sm" data-testid="timebase-open">登记时间证据</Button></DialogTrigger>
    <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
      <DialogHeader>
        <DialogTitle>时间基准证据与审核</DialogTitle>
        <DialogDescription>逐 DataAsset 登记绝对时间与可核查来源。填写和审核不会直接将声电同步标为已验证。</DialogDescription>
      </DialogHeader>
      {assetsQuery.isLoading && <p role="status">正在读取实验 DataAsset…</p>}
      {assetsQuery.error && <p role="alert" className="text-destructive">读取 DataAsset 失败：{assetsQuery.error.message}</p>}
      {assetsQuery.isSuccess && assets.length === 0 && <p role="alert">该实验没有已登记 DataAsset，不能提交时间锚点。</p>}
      {!record && assets.length > 0 && <div className="space-y-4">
        {validationsQuery.isError && <p role="alert" className="text-sm text-destructive">读取已有时间基准审计记录失败：{validationsQuery.error.message}</p>}
        {(validationsQuery.data?.data.validations ?? []).length > 0 && <section className="space-y-2 rounded-md border p-3" aria-label="已有审核记录">
          <h3 className="text-sm font-medium">已有提案 / 可恢复审核</h3>
          {(validationsQuery.data?.data.validations ?? []).map(item => <div key={item.validation_id} className="flex flex-wrap items-center gap-2 text-xs">
            <Badge variant="outline">{item.effective_status ?? item.status}</Badge>
            {item.evidence_integrity_status && <Badge variant="outline">证据：{item.evidence_integrity_status}</Badge>}
            <code>{item.validation_id}</code><span>assets: {item.asset_ids.join(", ")}</span>
            {evidenceIntegrityMessage(item.evidence_integrity_status) && <p role="alert" className="w-full text-destructive">{evidenceIntegrityMessage(item.evidence_integrity_status)}</p>}
            <Button size="sm" variant="ghost" disabled={loadingRecordId !== null} onClick={() => {
              setLoadingRecordId(item.validation_id);
              setLoadError(null);
              void client.getTimebaseValidation(batteryId, experimentId, item.validation_id)
                .then(result => setRecord(result.data))
                .catch(error => setLoadError(error instanceof Error ? error.message : String(error)))
                .finally(() => setLoadingRecordId(null));
            }}>{loadingRecordId === item.validation_id ? "读取中…" : "打开记录"}</Button>
          </div>)}
          {loadError && <p role="alert" className="text-destructive">打开失败：{loadError}</p>}
        </section>}
        <p className="rounded-md border p-3 text-sm">需要每个资产的明确绝对起始时间（ISO-8601，含 UTC offset，例如 `2024-01-06T21:03:01+08:00`）、时区、相对 `data/raw/` 的证据文件路径和该文件 SHA-256。服务器会核对文件存在、路径未越界及 checksum 一致；文件可放在实验目录下的 `timebase_evidence/`。不可用电脑本地时区或文件名代替设备证据。</p>
        <label className="block text-sm">IANA 时区<Input aria-label="IANA 时区" placeholder="如 Asia/Shanghai；须由实验记录确认" value={timezone} onChange={event => setTimezone(event.target.value)} /></label>
        <label className="block text-sm">允许误差（秒）<Input aria-label="允许误差（秒）" type="number" min="0.000001" step="any" value={tolerance} onChange={event => setTolerance(event.target.value)} /></label>
        {assets.map((asset: ExperimentDataAsset) => <fieldset key={asset.asset_id} className="space-y-2 rounded-md border p-3" data-testid={`timebase-asset-${asset.asset_id}`}>
          <legend className="px-1 text-sm font-medium">{asset.asset_id} · {asset.modality} · {asset.relative_path}</legend>
          <label className="block text-xs">绝对起始时间（含 UTC offset）<Input aria-label={`${asset.asset_id} 绝对起始时间`} placeholder="2024-01-06T21:03:01+08:00" value={initializedDrafts[asset.asset_id]?.absoluteStartTime ?? ""} onChange={event => patchDraft(asset.asset_id, { absoluteStartTime: event.target.value })} /></label>
          <label className="block text-xs">时间来源文件路径（相对 data/raw）<Input aria-label={`${asset.asset_id} 来源引用`} placeholder={`batteries/${batteryId}/${experimentId}/timebase_evidence/clock-log.csv`} value={initializedDrafts[asset.asset_id]?.sourceReference ?? ""} onChange={event => patchDraft(asset.asset_id, { sourceReference: event.target.value })} /></label>
          <label className="block text-xs">来源文件 SHA-256（与服务器核验值一致）<Input aria-label={`${asset.asset_id} 来源 SHA-256`} value={initializedDrafts[asset.asset_id]?.sourceSha256 ?? ""} onChange={event => patchDraft(asset.asset_id, { sourceSha256: event.target.value })} /></label>
        </fieldset>)}
        <label className="block text-sm">锚点证据文件路径（相对 data/raw，每行一项）<textarea className="w-full rounded-md border bg-transparent p-2 text-sm" rows={2} value={submissionEvidence} onChange={event => setSubmissionEvidence(event.target.value)} /></label>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            onClick={() => preflight.mutate(preflightRefs)}
            disabled={!preflightRefs.length || preflight.isPending}
            data-testid="timebase-evidence-preflight"
          >{preflight.isPending ? "读取并计算 SHA-256…" : "预检路径并自动填入 SHA-256"}</Button>
          <span className="text-xs muted">服务器只读取 raw 文件并计算 hash/大小；不会上传、复制或验证时钟科学语义。</span>
        </div>
        {preflight.error && JSON.stringify(preflight.variables) === JSON.stringify(preflightRefs) && <p role="alert" className="text-sm text-destructive">证据文件预检失败：{preflight.error.message}。检查 raw-relative 路径后重试；不会提交审核或改变同步状态。</p>}
        {preflightIsCurrent && preflight.data && <p role="status" data-testid="timebase-evidence-preflight-result" className="text-xs">已核验 {Object.keys(preflight.data.data.verified_evidence).length} 个证据文件；来源 SHA-256 已自动填入。完整性已核验不等于时钟已校准。</p>}
        <p className="text-xs muted">提交时后端会核验这些 raw-relative 文件并记录计算出的 SHA-256/字节数；这里只登记引用，不上传或修改原始文件。证据文件存在且 checksum 一致只证明文件完整性，不证明其科学上足以验证时钟。</p>
        {submit.error && <p role="alert" className="text-sm text-destructive">提交失败：{submit.error.message}</p>}
        <DialogFooter><Button onClick={() => submit.mutate()} disabled={!canSubmit || submit.isPending}>{submit.isPending ? "提交中…" : "提交为 PROVISIONAL"}</Button></DialogFooter>
      </div>}
      {record && <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{record.status}</Badge>
          {record.effective_status && record.effective_status !== record.status && <Badge variant="destructive">当前状态：{record.effective_status}</Badge>}
          {record.evidence_integrity_status && <Badge variant="outline" data-testid="timebase-current-evidence-integrity">当前证据：{record.evidence_integrity_status}</Badge>}
          {record.latest_review_evidence_integrity && <Badge variant="outline" data-testid="timebase-evidence-integrity">review evidence files {record.latest_review_evidence_integrity}</Badge>}
          {!record.latest_review_evidence_integrity && record.evidence_integrity && <Badge variant="outline" data-testid="timebase-evidence-integrity">submission evidence files {record.evidence_integrity}</Badge>}
          <code className="text-xs">{record.validation_id}</code></div>
        <p role="status" className="rounded-md border p-3 text-sm">{record.status === "PROVISIONAL" ? "锚点已提交，等待审核。" : record.status === "ACCEPTED_PENDING_RECOMPUTE" ? "审核声明已记录；需运行同步重算，validated_sync 保持 false。" : record.status === "RECOMPUTED_PROVISIONAL" ? "已接受锚点已写入 provisional 时间锚点状态；冲突/覆盖诊断仍须检查，声电同步尚未 validated。" : record.status === "REVOKED_PENDING_RECOMPUTE" ? "接受记录已撤销；当前处理工件仍需重算以恢复非该提案的锚点。" : record.status}</p>
        {evidenceIntegrityMessage(record.evidence_integrity_status) && <p role="alert" className="rounded-md border border-destructive p-3 text-sm">{evidenceIntegrityMessage(record.evidence_integrity_status)}</p>}
        {record.status === "PROVISIONAL" && <>
          <p className="text-sm font-medium">操作者审核（当前身份未经登录认证；这是审计声明，不等同于独立审核认证）</p>
          <label className="block text-sm">操作者身份<Input aria-label="操作者身份" value={operator} onChange={event => setOperator(event.target.value)} /></label>
          <label className="block text-sm">审核理由<textarea className="w-full rounded-md border bg-transparent p-2 text-sm" rows={2} value={rationale} onChange={event => setRationale(event.target.value)} /></label>
          {assets.map(asset => <fieldset key={asset.asset_id} className="space-y-2 rounded-md border p-3">
            <legend className="px-1 text-sm">{asset.asset_id} 审核结果</legend>
            <label className="block text-xs">对照校准/同步证据的误差（秒）<Input aria-label={`${asset.asset_id} 误差（秒）`} type="number" step="any" value={initializedDrafts[asset.asset_id]?.error ?? ""} onChange={event => patchDraft(asset.asset_id, { error: event.target.value })} /></label>
            <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={initializedDrafts[asset.asset_id]?.ambiguityFree ?? false} onChange={event => patchDraft(asset.asset_id, { ambiguityFree: event.target.checked })} />已检查该资产无未解决时间歧义</label>
          </fieldset>)}
          <label className="block text-sm">审核证据文件路径（相对 data/raw，每行一项）<textarea className="w-full rounded-md border bg-transparent p-2 text-sm" rows={2} value={reviewEvidence} onChange={event => setReviewEvidence(event.target.value)} /></label>
          {review.error && <p role="alert" className="text-sm text-destructive">审核未通过：{review.error.message}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => review.mutate("REJECT")} disabled={!operator.trim() || !rationale.trim() || review.isPending}>拒绝该提案</Button>
            <Button onClick={() => review.mutate("ACCEPT")} disabled={!canAccept || review.isPending || evidenceBlocked}>记录审核接受</Button>
          </DialogFooter>
        </>}
        {(record.status === "ACCEPTED_PENDING_RECOMPUTE" || record.status === "RECOMPUTED_PROVISIONAL") && <div className="space-y-2 rounded-md border p-3">
          <p className="text-sm">如审核证据后来被发现无效，可记录撤销并重算回到非该提案的时间锚点。撤销不会将同步标为已验证。</p>
          <label className="block text-sm">撤销操作者身份<Input aria-label="撤销操作者身份" value={operator} onChange={event => setOperator(event.target.value)} /></label>
          <label className="block text-sm">撤销理由<textarea aria-label="撤销理由" className="w-full rounded-md border bg-transparent p-2 text-sm" rows={2} value={rationale} onChange={event => setRationale(event.target.value)} /></label>
        </div>}
        {(record.status === "ACCEPTED_PENDING_RECOMPUTE" || record.status === "RECOMPUTED_PROVISIONAL") && <Button variant="outline" onClick={() => review.mutate("REVOKE")} disabled={!operator.trim() || !rationale.trim() || review.isPending}>撤销审核接受</Button>}
        {(record.status === "ACCEPTED_PENDING_RECOMPUTE" || record.status === "REVOKED_PENDING_RECOMPUTE") && <div className="space-y-2 rounded-md border p-3">
          <p className="text-sm">重新生成时间锚点、时间戳和同步关联；这是 provisional 重算，不是独立科学验证。</p>
          <Button onClick={() => recompute.mutate()} disabled={recompute.isPending || recomputeBlocked}>{recompute.isPending ? "正在重算…" : record.status === "REVOKED_PENDING_RECOMPUTE" ? "重算并撤销已应用锚点" : "应用已接受锚点并重算同步"}</Button>
          {recompute.error && <p role="alert" className="text-sm text-destructive">重算失败：{recompute.error.message}</p>}
          {recomputeRun && <p role="status" className="text-xs">运行状态：{String(recomputeRun.state ?? "已提交")} · <code>{String(recomputeRun.run_id ?? "run ID unavailable")}</code></p>}
        </div>}
        {review.isPending && <p role="status">正在写入审计事件…</p>}
        <p className="text-xs muted">VALIDATED 状态只会在认证审核、同步产物重算及独立验证全部完成后产生；该表单不会生成 validated_sync。</p>
        {record.events && <details className="rounded-md border p-3 text-xs"><summary>审计事件记录（{record.events.length}）</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap">{JSON.stringify(record.events, null, 2)}</pre></details>}
      </div>}
    </DialogContent>
  </Dialog>;
}
