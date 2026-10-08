import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, client } from "../../api/client";
import { Button } from "../ui/button";

const MAX_BYTES = 4_000_000;

export function CycleStepMappingPreflight({ batteryId, experimentId }: {
  batteryId: string;
  experimentId: string;
}) {
  const [file, setFile] = useState<File | null>(null);
  const preflight = useMutation({
    mutationFn: async (selected: File) =>
      client.preflightCycleStepMapping(batteryId, experimentId, await selected.text()),
  });

  const result = preflight.data?.data;
  const error = preflight.error;
  const errorReason = error instanceof ApiError
    ? String(error.details.reason ?? error.message)
    : error instanceof Error ? error.message : "预检失败，请稍后重试。";

  function selectFile(selected: File | null) {
    setFile(selected);
    preflight.reset();
  }

  return <section className="feature-card mt-5" data-testid="cycle-step-mapping-preflight">
    <h3 className="text-base">Cycle–Step 映射预检</h3>
    <p className="muted text-sm mt-1">
      对多个 Electrical XLSX 的 source-local Cycle/Step 建立显式对应时，可上传已审核的 CSV 检查覆盖和来源证据。
      系统不会根据文件名或循环编号推断对应关系。
    </p>
    <div className="mt-3 flex flex-wrap items-end gap-3">
      <label className="text-sm">
        <span className="block mb-1">选择映射 CSV（≤ 4 MB）</span>
        <input
          type="file"
          accept=".csv,text/csv"
          aria-label="选择 Cycle-Step 映射 CSV"
          data-testid="cycle-step-mapping-file"
          onChange={event => selectFile(event.currentTarget.files?.[0] ?? null)}
        />
      </label>
      <Button
        type="button"
        disabled={!file || file.size > MAX_BYTES || preflight.isPending}
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
        预检接口不会保存文件，也不会授权标签生成。保存到 annotations sidecar 后，正式流水线仍会重新核验。
      </p>
    </div>}
  </section>;
}
