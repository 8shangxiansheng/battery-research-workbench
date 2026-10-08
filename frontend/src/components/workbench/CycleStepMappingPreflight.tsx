import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE, ApiError, client } from "../../api/client";
import { Button } from "../ui/button";

const MAX_BYTES = 4_000_000;

export function CycleStepMappingPreflight({ batteryId, experimentId }: {
  batteryId: string;
  experimentId: string;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [confirmReviewed, setConfirmReviewed] = useState(false);
  const [showRevisionHistory, setShowRevisionHistory] = useState(false);
  const queryClient = useQueryClient();
  const activeMapping = useQuery({
    queryKey: ["cycle-step-mapping", batteryId, experimentId],
    queryFn: () => client.getCycleStepMappingStatus(batteryId, experimentId),
  });
  const preflight = useMutation({
    mutationFn: async (selected: File) =>
      client.preflightCycleStepMapping(batteryId, experimentId, await selected.text()),
  });
  const revisions = useQuery({
    queryKey: ["cycle-step-mapping-revisions", batteryId, experimentId],
    queryFn: () => client.getCycleStepMappingRevisions(batteryId, experimentId),
    enabled: showRevisionHistory,
  });
  const save = useMutation({
    mutationFn: async (selected: File) => client.saveCycleStepMapping(batteryId, experimentId, {
      mapping_csv: await selected.text(),
      confirm_reviewed: true,
      expected_active_sha256: activeMapping.data?.data.active_mapping_sha256 ?? null,
    }),
    onSuccess: async () => Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["cycle-step-mapping", batteryId, experimentId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["cycle-step-mapping-revisions", batteryId, experimentId],
      }),
    ]),
    onError: error => {
      if (error instanceof ApiError && error.code === "CONFLICT") {
        preflight.reset();
        setConfirmReviewed(false);
        void Promise.all([
          queryClient.invalidateQueries({
            queryKey: ["cycle-step-mapping", batteryId, experimentId],
          }),
          queryClient.invalidateQueries({
            queryKey: ["cycle-step-mapping-revisions", batteryId, experimentId],
          }),
        ]);
      }
    },
  });

  const result = preflight.data?.data;
  const error = preflight.error;
  const errorReason = error instanceof ApiError
    ? String(error.details.reason ?? error.message)
    : error instanceof Error ? error.message : "预检失败，请稍后重试。";
  const saveErrorReason = save.error instanceof ApiError
    ? String(save.error.details.reason ?? save.error.message)
    : save.error instanceof Error ? save.error.message : "保存失败，请重新读取当前映射状态。";
  const activeMappingApiError = activeMapping.error instanceof ApiError
    ? activeMapping.error
    : null;
  const revisionHistoryBlocked = activeMappingApiError?.code === "INTEGRITY_ERROR";

  function selectFile(selected: File | null) {
    setFile(selected);
    preflight.reset();
    save.reset();
    setConfirmReviewed(false);
  }

  function reloadCurrentMapping() {
    preflight.reset();
    save.reset();
    setConfirmReviewed(false);
    void activeMapping.refetch();
  }

  return <section className="feature-card mt-5" data-testid="cycle-step-mapping-preflight">
    <h3 className="text-base">Cycle–Step 映射预检</h3>
    <p className="muted text-sm mt-1">
      对多个 Electrical XLSX 的 source-local Cycle/Step 建立显式对应时，可上传已审核的 CSV 检查覆盖和来源证据。
      系统不会根据文件名或循环编号推断对应关系。
    </p>
    {activeMapping.isLoading && <p role="status" className="muted text-xs mt-2">正在读取当前映射版本…</p>}
    {activeMapping.isError && <div role="alert" className="text-sm text-destructive mt-2">
      {revisionHistoryBlocked ? <>
        <p>映射历史快照完整性校验未通过；系统已阻止读取/覆盖，当前映射不会被自动修复。</p>
        <p className="mt-1">请先备份并从可信副本恢复该实验的 <code>data/annotations/{"{battery_id}/{experiment_id}"}</code> 目录，再重试。不要删除或改写损坏快照来绕过校验。</p>
        <details className="mt-1">
          <summary>支持信息</summary>
          <p>{activeMappingApiError?.message}</p>
          <p>请求 ID：{activeMappingApiError?.requestId}</p>
        </details>
      </> : <p>无法读取当前映射版本；为避免覆盖已有版本，暂不能保存。请重试或检查服务状态。</p>}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="ml-2"
        disabled={activeMapping.isFetching}
        onClick={() => void activeMapping.refetch()}
      >
        {activeMapping.isFetching ? "正在重试…" : "重试读取映射状态"}
      </Button>
    </div>}
    {activeMapping.data && <p className="muted text-xs mt-2" data-testid="cycle-step-mapping-current">
      {activeMapping.data.data.status === "MISSING" ? "当前没有已保存映射" :
        activeMapping.data.data.status === "VALIDATED" ? "当前映射结构与来源 checksum 已验证" :
          `当前映射无效或过期：${activeMapping.data.data.reason ?? "需要重新预检"}`}
      {` · 历史版本 ${activeMapping.data.data.revision_count}`}
      {activeMapping.data.data.active_mapping_sha256
        ? ` · 当前版本 ${activeMapping.data.data.active_mapping_sha256.slice(0, 12)}` : ""}
    </p>}
    {activeMapping.data?.data.status === "INVALID" && <p className="muted text-xs mt-1" role="note">
      恢复方式：根据当前 parser/raw 证据修订映射，重新预检并确认后保存新版本；旧版本会保留在历史快照中。
    </p>}
    {activeMapping.data && <div className="mt-2">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setShowRevisionHistory(value => !value)}
        aria-expanded={showRevisionHistory}
        data-testid="cycle-step-mapping-toggle-history"
      >
        {showRevisionHistory ? "隐藏版本历史" : `查看版本历史（${activeMapping.data.data.revision_count}）`}
      </Button>
      {showRevisionHistory && <div className="mt-2 rounded-md border p-3" data-testid="cycle-step-mapping-history">
        <p className="muted text-xs mb-2">历史列表按内容 SHA-256 标识；下载的是保存时的原始 CSV 字节，不代表该历史版本仍匹配当前 parser/raw。</p>
        {revisions.isLoading && <p role="status" className="muted text-sm">正在读取版本历史…</p>}
        {revisions.isError && <div role="alert" className="text-sm text-destructive">
          <p>{revisions.error instanceof Error ? revisions.error.message : "无法读取版本历史。"}</p>
          <Button type="button" variant="outline" size="sm" className="mt-2" onClick={() => void revisions.refetch()}>
            重试读取历史
          </Button>
        </div>}
        {revisions.data && revisions.data.data.revisions.length === 0 && <p className="muted text-sm">暂无已保存快照。</p>}
        {revisions.data && revisions.data.data.revisions.length > 0 && <ul className="space-y-2">
          {revisions.data.data.revisions.map(revision => <li
            key={revision.sha256}
            className="flex flex-wrap items-center justify-between gap-2 text-xs"
          >
            <span>
              <code>{revision.sha256}</code>
              {` · ${revision.size_bytes} bytes`}
              {revision.is_active ? <span className="ml-2">当前活动版本</span> : null}
            </span>
            <a
              className="underline underline-offset-2"
              href={`${API_BASE}/experiments/${encodeURIComponent(batteryId)}/${encodeURIComponent(experimentId)}/cycle-step-mapping/revisions/${revision.sha256}`}
              download={`cycle-step-mapping-${revision.sha256}.csv`}
            >
              下载 CSV
            </a>
          </li>)}
        </ul>}
      </div>}
    </div>}
    <div className="mt-3 flex flex-wrap items-end gap-3">
      <label className="text-sm">
        <span className="block mb-1">选择映射 CSV（≤ 4 MB）</span>
        <input
          type="file"
          accept=".csv,text/csv"
          aria-label="选择 Cycle-Step 映射 CSV"
          data-testid="cycle-step-mapping-file"
          onChange={event => {
            selectFile(event.currentTarget.files?.[0] ?? null);
            event.currentTarget.value = "";
          }}
        />
      </label>
      <Button asChild variant="outline">
        <a href="/cycle-step-mapping.csv" download="cycle-step-mapping.csv">
          下载空白 CSV 模板
        </a>
      </Button>
      <Button
        type="button"
        disabled={!file || file.size > MAX_BYTES || preflight.isPending || save.isPending}
        onClick={() => file && preflight.mutate(file)}
        data-testid="cycle-step-mapping-run-preflight"
      >
        {preflight.isPending ? "正在预检…" : "预检映射"}
      </Button>
    </div>
    {file && <p className="muted text-xs mt-2" data-testid="cycle-step-mapping-file-name">
      {file.name} · {(file.size / 1024).toFixed(1)} KB
    </p>}
    {file && file.size > MAX_BYTES && <p role="alert" className="text-sm text-destructive mt-2">
      文件超过 4 MB。请缩小 CSV 后重试。
    </p>}
    {preflight.isError && <div role="alert" className="notice mt-3 text-sm" data-testid="cycle-step-mapping-error">
      <strong>映射未通过预检</strong>
      <p className="mt-1">{errorReason}</p>
      <p className="muted mt-1">检查 CSV 列、source step 覆盖、parser manifest checksum 与 evidence 文件后再试。</p>
    </div>}
    {result && <div role="status" className="notice mt-3 text-sm" data-testid="cycle-step-mapping-result">
      <strong>结构与字节校验通过</strong>
      <dl className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
        <div><dt className="muted">来源 Cycle</dt><dd>{result.source_cycle_count}</dd></div>
        <div><dt className="muted">来源 Step</dt><dd>{result.source_step_count}</dd></div>
        <div><dt className="muted">Canonical Cycle</dt><dd>{result.canonical_cycle_count}</dd></div>
        <div><dt className="muted">审核声明</dt><dd>{result.review_status}</dd></div>
      </dl>
      <p className="mt-2">
        这只证明映射结构和文件 checksum 一致；审核人身份及 Cycle 连续性的科学解释未验证。
        预检本身不会保存或授权标签生成。只有通过预检并明确确认人工审核后，才可写入 annotations sidecar；正式流水线仍会重新核验。
      </p>
      <label className="flex items-start gap-2 mt-3">
        <input
          type="checkbox"
          checked={confirmReviewed}
          onChange={event => setConfirmReviewed(event.currentTarget.checked)}
          data-testid="cycle-step-mapping-confirm-reviewed"
        />
        <span>我已根据证据逐项审核 CSV 中的 Cycle/Step 对应关系；此确认不代表系统认证审核人身份。</span>
      </label>
      <Button
        type="button"
        className="mt-3"
        disabled={!file || !confirmReviewed || activeMapping.isLoading || activeMapping.isError || save.isPending}
        onClick={() => file && save.mutate(file)}
        data-testid="cycle-step-mapping-save"
      >
        {save.isPending ? "正在保存版本…" : "保存已审核映射"}
      </Button>
    </div>}
    {save.isError && <div role="alert" className="notice mt-3 text-sm" data-testid="cycle-step-mapping-save-error">
      {save.error instanceof ApiError && save.error.code === "CONFLICT"
        ? "检测到映射版本冲突；当前版本未被覆盖。系统已重新读取状态，请重新选择/预检文件并再次确认后保存。"
        : `${saveErrorReason}。当前版本未被覆盖；请重新读取状态并再次预检。`}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="mt-2"
        disabled={activeMapping.isFetching}
        onClick={reloadCurrentMapping}
      >
        {activeMapping.isFetching ? "正在刷新…" : "刷新状态并重新审核"}
      </Button>
    </div>}
    {save.data && <p role="status" className="notice mt-3 text-sm" data-testid="cycle-step-mapping-saved">
      {save.data.data.save_status === "ALREADY_CURRENT" ? "此映射版本已是当前版本。" : "映射已保存并创建不可变版本快照。"}
      {` 当前历史版本数：${save.data.data.revision_count}。`}
      保存位置：<code>{save.data.data.active_mapping_relative_path}</code>。
      <span className="block mt-1">这记录的是操作者声明和文件完整性，不证明物理 Cycle 连续性。</span>
    </p>}
  </section>;
}
