import { useState } from "react";
import type { CycleStepMappingSourceStep } from "../../api/client";
import { Button } from "../ui/button";

type MappingRow = CycleStepMappingSourceStep & {
  canonical_cycle_index: string;
  canonical_step_index: string;
};

type CycleStepMappingEditorProps = {
  sourceSteps: CycleStepMappingSourceStep[];
  isPending: boolean;
  onPreflight: (mappingCsv: string) => void;
  onChange: () => void;
};

function csvCell(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}

export function CycleStepMappingEditor({
  sourceSteps,
  isPending,
  onPreflight,
  onChange,
}: CycleStepMappingEditorProps) {
  const [rows, setRows] = useState<MappingRow[]>(() => sourceSteps.map(row => ({ ...row })));
  const [mappingId, setMappingId] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [reviewedAt, setReviewedAt] = useState("");
  const [rationale, setRationale] = useState("");
  const [reviewed, setReviewed] = useState(false);

  const assignmentsComplete = rows.length > 0 && rows.every(row => {
    const canonicalCycle = Number(row.canonical_cycle_index);
    const canonicalStep = Number(row.canonical_step_index);
    return Number.isInteger(canonicalCycle) && canonicalCycle > 0
      && Number.isInteger(canonicalStep) && canonicalStep > 0;
  });
  const timestampHasOffset = /(?:Z|[+-]\d{2}:\d{2})$/i.test(reviewedAt.trim())
    && Number.isFinite(Date.parse(reviewedAt));
  const canPreflight = assignmentsComplete && mappingId.trim() !== ""
    && reviewer.trim() !== "" && timestampHasOffset
    && rationale.trim() !== "" && reviewed;

  function updateRow(index: number, patch: Partial<MappingRow>) {
    onChange();
    setRows(current => current.map((row, rowIndex) =>
      rowIndex === index ? { ...row, ...patch } : row,
    ));
  }

  function buildCsv(): string {
    const fields = [
      "contract_version",
      "mapping_id",
      "battery_id",
      "experiment_id",
      "electrical_asset_id",
      "cycle_index_raw",
      "step_index_raw",
      "canonical_cycle_index",
      "canonical_step_index",
      "parser_manifest_sha256",
      "evidence_relative_path",
      "evidence_sha256",
      "review_status",
      "reviewer",
      "reviewed_at",
      "rationale",
    ];
    const lines = [fields.map(csvCell).join(",")];
    for (const row of rows) {
      const values = [
        row.contract_version,
        mappingId.trim(),
        row.battery_id,
        row.experiment_id,
        row.electrical_asset_id,
        row.cycle_index_raw,
        row.step_index_raw,
        row.canonical_cycle_index,
        row.canonical_step_index,
        row.parser_manifest_sha256,
        row.evidence_relative_path,
        row.evidence_sha256,
        reviewed ? "ACCEPTED" : "",
        reviewer.trim(),
        reviewedAt.trim(),
        rationale.trim(),
      ];
      lines.push(values.map(csvCell).join(","));
    }
    return `${lines.join("\n")}\n`;
  }

  return <div className="mt-3 rounded-md border p-3" data-testid="cycle-step-mapping-editor">
    <p className="text-sm">
      每一行都是 parser 确认存在的 source Cycle/Step。请依据实验记录手动填写 canonical 对应；空白模板不包含任何自动匹配建议。
    </p>
    <div className="mt-3 grid gap-3 sm:grid-cols-2">
      <label className="text-sm">
        <span className="block mb-1">映射 ID</span>
        <input className="w-full rounded border px-2 py-1" value={mappingId}
        onChange={event => { onChange(); setMappingId(event.currentTarget.value); }} />
      </label>
      <label className="text-sm">
        <span className="block mb-1">审核人声明</span>
        <input className="w-full rounded border px-2 py-1" value={reviewer}
          onChange={event => { onChange(); setReviewer(event.currentTarget.value); }} />
      </label>
      <label className="text-sm">
        <span className="block mb-1">审核时间（ISO-8601，必须带时区）</span>
        <input className="w-full rounded border px-2 py-1" placeholder="2026-10-08T10:00:00+08:00"
          value={reviewedAt} onChange={event => { onChange(); setReviewedAt(event.currentTarget.value); }} />
      </label>
      <label className="text-sm">
        <span className="block mb-1">映射依据 / 理由</span>
        <input className="w-full rounded border px-2 py-1" value={rationale}
          onChange={event => { onChange(); setRationale(event.currentTarget.value); }} />
      </label>
    </div>
    <div className="mt-3 overflow-x-auto">
      <table className="w-full border-collapse text-left text-xs">
        <thead>
          <tr className="border-b">
            <th className="p-2">DataAsset</th>
            <th className="p-2">Source Cycle / Step</th>
            <th className="p-2">Canonical Cycle</th>
            <th className="p-2">Canonical Step</th>
            <th className="p-2">来源文件 / SHA-256</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => <tr
            className="border-b align-top"
            key={`${row.electrical_asset_id}:${row.cycle_index_raw}:${row.step_index_raw}`}
          >
            <td className="p-2"><code>{row.electrical_asset_id}</code></td>
            <td className="p-2">{row.cycle_index_raw} / {row.step_index_raw}</td>
            <td className="p-2">
              <input aria-label={`Canonical Cycle ${row.electrical_asset_id} ${row.cycle_index_raw}/${row.step_index_raw}`}
                className="w-24 rounded border px-2 py-1" type="number" min="1" step="1"
                value={row.canonical_cycle_index}
                onChange={event => updateRow(index, { canonical_cycle_index: event.currentTarget.value })} />
            </td>
            <td className="p-2">
              <input aria-label={`Canonical Step ${row.electrical_asset_id} ${row.cycle_index_raw}/${row.step_index_raw}`}
                className="w-24 rounded border px-2 py-1" type="number" min="1" step="1"
                value={row.canonical_step_index}
                onChange={event => updateRow(index, { canonical_step_index: event.currentTarget.value })} />
            </td>
            <td className="p-2">
              <code>{row.evidence_relative_path}</code><br />
              <code>{row.evidence_sha256.slice(0, 12)}…</code>
            </td>
          </tr>)}
        </tbody>
      </table>
    </div>
    <label className="mt-3 flex items-start gap-2 text-sm">
      <input type="checkbox" checked={reviewed} onChange={event => {
        onChange();
        setReviewed(event.currentTarget.checked);
      }} />
      <span>我已依据可追溯实验记录逐项审核映射；系统不认证审核人身份，也不独立证明物理 Cycle 连续性。</span>
    </label>
    {!assignmentsComplete && <p className="mt-2 text-xs text-amber-700">请为每个 source step 填写正整数 canonical Cycle 和 Step。</p>}
    {!timestampHasOffset && reviewedAt && <p className="mt-2 text-xs text-amber-700">
      审核时间需要是有效 ISO-8601 时间并包含 UTC offset，例如 <code>+08:00</code> 或 <code>Z</code>。
    </p>}
    {!canPreflight && <p className="muted mt-2 text-xs" role="status">
      填完所有映射、审核元数据并勾选人工审核声明后，才能运行结构与来源校验；此操作不会保存。
    </p>}
    <Button type="button" className="mt-3" disabled={!canPreflight || isPending}
      onClick={() => onPreflight(buildCsv())} data-testid="cycle-step-mapping-editor-preflight">
      {isPending ? "正在预检…" : "预检人工填写的映射"}
    </Button>
  </div>;
}
