/**
 * 运行记录 + UserActionRequired 端到端（§41-42）。
 * WAITING_FOR_USER → 显示原因 → 收集输入 → POST action → resume → 更新状态。
 * 轮询（polling），不用 WebSocket（§42）。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";

const STATUS_LABELS: Record<string, string> = {
  SUCCEEDED: "成功",
  RUNNING: "运行中",
  WAITING_FOR_USER: "等待用户输入",
  FAILED: "失败",
  PARTIAL: "部分完成",
};

export function RunsPage() {
  const qc = useQueryClient();
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [actionValues, setActionValues] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<unknown>(null);
  const [flowMessage, setFlowMessage] = useState<string | null>(null);

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

      {runs.isLoading ? (
        <p role="status">加载运行记录…</p>
      ) : runs.error ? (
        <ErrorBanner error={runs.error} />
      ) : (runs.data?.data.runs.length ?? 0) === 0 ? (
        <p data-testid="no-runs">暂无运行记录。</p>
      ) : (
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
            <pre style={{ background: "#f6f6f6", padding: "0.5rem", overflowX: "auto" }}>
              {JSON.stringify(runDetail.data?.data, null, 2)}
            </pre>
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
                    <p>
                      <small>
                        客户端只做纯单位换算成 Hz 提交；不猜数值；不把 frame cadence
                        当采样率（§14）。
                      </small>
                    </p>
                  </fieldset>
                ) : (
                  <p>
                    <small>required_fields: {JSON.stringify(a.required_fields)}</small>
                  </p>
                )}
                <button
                  type="button"
                  data-testid="submit-action"
                  disabled={submitAction.isPending}
                  onClick={() => {
                    const values: Record<string, unknown> = { ...actionValues };
                    if (values["ultrasound.sampling_rate_hz"] !== undefined) {
                      const unit = (values["fs_unit"] as string) ?? "MHz";
                      const multipliers: Record<string, number> = { Hz: 1, kHz: 1e3, MHz: 1e6 };
                      values["ultrasound.sampling_rate_hz"] =
                        Number(values["ultrasound.sampling_rate_hz"]) * (multipliers[unit] ?? 1);
                      delete values["fs_unit"];
                    }
                    submitAction.mutate({ actionId: a.action_id, values });
                  }}
                >
                  提交动作（POST user-actions）
                </button>
                <button
                  type="button"
                  data-testid="resume-run"
                  disabled={resume.isPending}
                  onClick={() => resume.mutate()}
                >
                  Resume
                </button>
              </div>
            ))
          )}
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
