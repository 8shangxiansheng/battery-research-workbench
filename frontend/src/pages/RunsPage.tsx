/**
 * 运行记录 + UserActionRequired 端到端（§41-42）。
 * WAITING_FOR_USER → 显示原因 → 收集输入 → POST action → resume → 更新状态。
 * 轮询（polling），不用 WebSocket（§42）。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { client } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";
import { useInvalidateWorkflow, useWorkflowContext } from "../hooks/useWorkflowContext";

const STATUS_LABELS: Record<string, string> = {
  SUCCEEDED: "成功",
  RUNNING: "运行中",
  WAITING_FOR_USER: "等待用户输入",
  FAILED: "失败",
  PARTIAL: "部分完成",
};

export function RunsPage() {
  const qc = useQueryClient();
  const { batteryId = "", experimentId = "" } = useParams();
  const workflow = useWorkflowContext(batteryId, experimentId);
  const invalidateWorkflow = useInvalidateWorkflow();
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [actionValues, setActionValues] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<unknown>(null);
  const [flowMessage, setFlowMessage] = useState<string | null>(null);
  const invalidModalities = workflow.data?.meta.invalid_modalities ?? [];
  const sourceIntegrityBlocked = workflow.data?.meta.source_integrity_status === "INTEGRITY_BLOCKED";
  const alignmentRecoveryRequired = workflow.data?.steps.ALIGNMENT?.blocking?.required_action
    === "REBUILD_TIME_ANCHORS_AND_DOWNSTREAM_ALIGNMENT";
  const reparse = useMutation({
    mutationFn: () => client.startRun({
      profile: "INGEST_TO_MEASUREMENT_EVENTS",
      battery_id: batteryId,
      experiment_id: experimentId,
      stages: invalidModalities.flatMap((modality) =>
        modality === "electrical"
          ? ["ELECTRICAL_CANONICAL"]
          : modality === "ultrasound"
            ? ["ULTRASOUND_CANONICAL"]
            : [],
      ),
    }),
    onSuccess: () => {
      setFlowMessage("来源重新解析已完成；请复核 lineage 后再继续下游分析。");
      invalidateWorkflow(batteryId, experimentId);
      void qc.invalidateQueries({ queryKey: ["runs"] });
    },
    onError: (error) => setActionError(error),
  });
  const rebuildAlignment = useMutation({
    mutationFn: () => client.startRun({
      profile: "INGEST_TO_MEASUREMENT_EVENTS",
      battery_id: batteryId,
      experiment_id: experimentId,
    }),
    onSuccess: (result) => {
      setFlowMessage("时间基准与下游同步链已提交重建；请检查运行结果和新的对齐状态。重建不会把时间基准标记为已验证。");
      setActionError(null);
      invalidateWorkflow(batteryId, experimentId);
      void qc.invalidateQueries({ queryKey: ["run", result.data.run_id] });
      void qc.invalidateQueries({ queryKey: ["runs"] });
      for (const key of ["synchronization", "alignment-summary", "alignment-samples", "alignment-exclusions"]) {
        void qc.invalidateQueries({ queryKey: [key, batteryId, experimentId] });
      }
    },
    onError: (error) => setActionError(error),
  });

  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => client.listRuns(),
    refetchInterval: 5000, // polling
  });

  const runDetail = useQuery({
    queryKey: ["run", selectedRun],
    queryFn: () => client.getRun(selectedRun!),
    enabled: selectedRun !== null,
  });
  const runActions = useQuery({
    queryKey: ["run-actions", selectedRun],
    queryFn: () => client.listUserActions(selectedRun!),
    enabled: selectedRun !== null,
  });

  const submitAction = useMutation({
    mutationFn: ({ actionId, values }: { actionId: string; values: Record<string, unknown> }) =>
      client.submitUserAction(selectedRun!, actionId, values),
    onSuccess: () => {
      setFlowMessage("动作已提交。正在 resume…");
      setActionError(null);
      resume.mutate();
    },
    onError: (e) => setActionError(e),
  });

  const resume = useMutation({
    mutationFn: () => client.resumeRun(selectedRun!),
    onSuccess: () => {
      setFlowMessage("运行已 resume。");
      void qc.invalidateQueries({ queryKey: ["run", selectedRun] });
      void qc.invalidateQueries({ queryKey: ["run-actions", selectedRun] });
      void qc.invalidateQueries({ queryKey: ["runs"] });
    },
    onError: (e) => setActionError(e),
  });

  const actions = runActions.data?.data.user_actions ?? [];

  return (
    <section aria-labelledby="runs-title">
      <h2 id="runs-title">运行记录 Runs</h2>

      {sourceIntegrityBlocked && (
        <section className="notice mb-5" role="alert" data-testid="source-integrity-recovery">
          <h3 className="font-medium">来源解析清单完整性阻断</h3>
          <p className="text-sm mt-1">
            {invalidModalities.length
              ? `受影响模态：${invalidModalities.join("、")}。将只重解析对应原始来源，不运行同步、特征或模型步骤。`
              : "系统未能确定可安全重解析的模态，请先检查原始来源清单。"}
          </p>
          <button
            type="button"
            data-testid="reparse-source-assets"
            disabled={!invalidModalities.length || reparse.isPending}
            onClick={() => reparse.mutate()}
          >
            {reparse.isPending ? "正在重新解析…" : "重新解析无效来源"}
          </button>
          {reparse.error && <ErrorBanner error={reparse.error} />}
        </section>
      )}

      {alignmentRecoveryRequired && (
        <section className="notice mb-5" role="alert" data-testid="timebase-chain-recovery">
          <h3 className="font-medium">时间基准 / 同步工件需要重建</h3>
          <p className="text-sm mt-1">
            当前时间锚点或 timestamp 来源、输出与现状不一致。运行完整导入与关联链以重建 TimeAnchor、timestamps、Synchronization 和 MeasurementEvents；这只修复工件新鲜度，不证明设备时钟准确，也不会将同步标记为已验证。
          </p>
          <button
            type="button"
            data-testid="rebuild-timebase-chain"
            disabled={rebuildAlignment.isPending}
            onClick={() => rebuildAlignment.mutate()}
          >
            {rebuildAlignment.isPending ? "正在提交重建…" : "重建时间基准与同步链"}
          </button>
          {rebuildAlignment.error && <ErrorBanner error={rebuildAlignment.error} />}
        </section>
      )}

      {runs.isLoading ? (
        <p role="status">加载运行记录…</p>
      ) : runs.error ? (
        <ErrorBanner error={runs.error} />
      ) : (runs.data?.data.runs.length ?? 0) === 0 ? (
        <p data-testid="no-runs">暂无运行记录。</p>
      ) : (
        <details data-testid="run-list-disclosure" open={selectedRun === null}>
          <summary>运行列表（{runs.data?.data.runs.length ?? 0} 条）</summary>
          <table data-testid="runs-table">
            <thead>
              <tr>
                <th>run_id</th>
                <th>状态</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(runs.data?.data.runs ?? []).map((r) => (
                <tr key={r.run_id}>
                  <td>
                    <code>{r.run_id}</code>
                  </td>
                  <td>
                    {r.status}（{STATUS_LABELS[r.status] ?? "未知"}）
                  </td>
                  <td>
                    <button type="button" onClick={() => setSelectedRun(r.run_id)}>
                      查看
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {selectedRun ? (
        <div data-testid="run-detail">
          <h3>
            运行详情 <code>{selectedRun}</code>
          </h3>
          {runDetail.isLoading ? (
            <p role="status">加载详情…</p>
          ) : runDetail.error ? (
            <ErrorBanner error={runDetail.error} />
          ) : (
            <details>
              <summary>查看运行技术详情（原始 JSON）</summary>
              <pre style={{ background: "#f6f6f6", padding: "0.5rem", overflowX: "auto" }}>
                {JSON.stringify(runDetail.data?.data, null, 2)}
              </pre>
            </details>
          )}

          <h4 data-testid="pending-actions-title">待处理科学动作（UserActionRequired）</h4>
          {actions.length === 0 ? (
            <p data-testid="no-pending-actions">无待处理动作。</p>
          ) : (
            actions.map((a) => (
              <div
                key={a.action_id}
                data-testid={`action-${a.action_type}`}
                style={{ border: "1px solid #d82", padding: "0.5rem", marginBottom: "0.5rem" }}
              >
                <p>
                  <strong>{a.action_type}</strong> — {a.message}
                </p>
                {a.scientific_reason ? (
                  <p>
                    <small>科学原因：{a.scientific_reason}</small>
                  </p>
                ) : null}
                {a.action_type === "MISSING_SAMPLING_RATE" ? (
                  <fieldset>
                    <legend>采样频率 Sampling Rate（仪器参数 — 不得猜值，§13-14）</legend>
                    <label htmlFor="fs-value">fs 数值：</label>
                    <input
                      id="fs-value"
                      data-testid="fs-input"
                      type="number"
                      min={0}
                      value={actionValues["ultrasound.sampling_rate_hz"] ?? ""}
                      onChange={(e) =>
                        setActionValues((prev) => ({
                          ...prev,
                          "ultrasound.sampling_rate_hz": e.target.value,
                        }))
                      }
                    />
                    <label htmlFor="fs-unit">单位：</label>
                    <select
                      id="fs-unit"
                      data-testid="fs-unit"
                      value={actionValues["fs_unit"] ?? "MHz"}
                      onChange={(e) => setActionValues((prev) => ({ ...prev, fs_unit: e.target.value }))}
                    >
                      <option value="Hz">Hz</option>
                      <option value="kHz">kHz</option>
                      <option value="MHz">MHz</option>
                    </select>
                    <label className="ml-3" htmlFor="fs-source">来源：</label>
                    <input
                      id="fs-source"
                      data-testid="fs-source"
                      className="border rounded px-2 py-1"
                      value={actionValues["fs_source"] ?? "实验记录"}
                      onChange={(e) => setActionValues((prev) => ({ ...prev, fs_source: e.target.value }))}
                    />
                    <label className="ml-3" htmlFor="fs-verification">核验状态：</label>
                    <select
                      id="fs-verification"
                      data-testid="fs-verification"
                      value={actionValues["fs_verification"] ?? "UNVERIFIED"}
                      onChange={(e) => setActionValues((prev) => ({ ...prev, fs_verification: e.target.value }))}
                    >
                      <option value="UNVERIFIED">UNVERIFIED（默认，未核验）</option>
                      <option value="VERIFIED">VERIFIED（本人已对照实验记录核验）</option>
                    </select>
                    <p>
                      <small>
                        按 {"{value, unit, source_reference, verification_status}"} 原样提交，后端负责换算成 Hz
                        并记录来源；不猜数值；不把 frame cadence 当采样率（§14）。
                      </small>
                    </p>
                  </fieldset>
                ) : (
                  <fieldset>
                    <legend>所需字段 Required fields（回声确认后端给出的值，不新造选择）</legend>
                    {(a.required_fields as { field?: string; value?: string }[]).map((rf) => {
                      const name = rf.field ?? "";
                      if (!name || name === "none") {
                        return <p key={`${a.action_id}-none`}><small>该动作无需附加字段 — 直接提交确认即可。</small></p>;
                      }
                      if (a.action_type === "CONFIRM_FEATURE_SELECTION" && name === "selection_id") {
                        return (
                          <div key={`${a.action_id}-${name}`} className="block text-sm mt-1">
                            {name}： <code>{rf.value ?? "—"}</code>
                            <small className="muted ml-2">后端生成的选择身份，只读回传，不可编辑。</small>
                          </div>
                        );
                      }
                      return (
                        <label key={`${a.action_id}-${name}`} className="block text-sm mt-1">
                          {name}：
                          <input
                            data-testid={`action-field-${name}`}
                            className="border rounded px-2 py-1 ml-2"
                            value={actionValues[name] ?? rf.value ?? ""}
                            onChange={(e) => setActionValues((prev) => ({ ...prev, [name]: e.target.value }))}
                          />
                          {rf.value ? <small className="muted ml-2">（后端建议值 {rf.value} 已预填）</small> : null}
                        </label>
                      );
                    })}
                  </fieldset>
                )}
                <button
                  type="button"
                  data-testid="submit-action"
                  disabled={submitAction.isPending}
                  onClick={() => {
                    const values: Record<string, unknown> = {};
                    for (const rf of a.required_fields as { field?: string; value?: string }[]) {
                      if (rf.field && rf.field !== "none" && rf.value !== undefined) values[rf.field] = rf.value;
                    }
                    Object.assign(values, actionValues);
                    if (values["ultrasound.sampling_rate_hz"] !== undefined) {
                      const unit = (values["fs_unit"] as string) ?? "MHz";
                      // orchestrator contract: submit the record fields as-is —
                      // the backend converts to Hz and derives provenance (§13-14)
                      values["ultrasound.sampling_rate_hz"] = {
                        value: Number(values["ultrasound.sampling_rate_hz"]),
                        unit,
                        source_reference: (values["fs_source"] as string) ?? "实验记录",
                        verification_status: (values["fs_verification"] as string) ?? "UNVERIFIED",
                      };
                      delete values["fs_unit"];
                      delete values["fs_source"];
                      delete values["fs_verification"];
                    }
                    submitAction.mutate({ actionId: a.action_id, values });
                  }}
                >
                  {a.action_type === "CONFIRM_FEATURE_SELECTION"
                    ? "确认上述特征并继续"
                    : a.action_type === "MISSING_SAMPLING_RATE"
                      ? "提交采样参数并继续"
                      : "提交并继续"}
                </button>
                <small className="muted ml-2">提交后运行会自动继续。</small>
              </div>
            ))
          )}
          {actions.length === 0 && runDetail.data?.data.status === "WAITING_FOR_USER" ? (
            <button
              type="button"
              data-testid="resume-run"
              disabled={resume.isPending}
              onClick={() => resume.mutate()}
            >
              恢复运行
            </button>
          ) : null}
          {flowMessage ? (
            <p role="status" data-testid="flow-message">
              {flowMessage}
            </p>
          ) : null}
          {actionError ? <ErrorBanner error={actionError} /> : null}
        </div>
      ) : null}
    </section>
  );
}
