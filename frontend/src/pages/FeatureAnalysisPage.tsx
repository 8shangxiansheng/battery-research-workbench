/**
 * 特征分析（§20-26）。
 * EXPLORATORY_FULL_DATA / TRAIN_ONLY_ML_SAFE 两种模式显式区分。
 * 不自动命名 "best feature"；redundancy 只 flag 不自动删除。
 * 确认特征选择走 UserActionRequired（§26）。
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { ApiError, client } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";

export function FeatureAnalysisPage() {
  const { batteryId = "", experimentId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [mode, setMode] = useState<"EXPLORATORY_FULL_DATA" | "TRAIN_ONLY_ML_SAFE">(
    "EXPLORATORY_FULL_DATA",
  );
  const [submitted, setSubmitted] = useState<{ analysisId: string; reused: boolean } | null>(
    searchParams.get("analysis_id")
      ? { analysisId: searchParams.get("analysis_id")!, reused: true }
      : null,
  );
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [candidates, setCandidates] = useState<string>("waveform_rms_a_u, amplitude_a_u");

  const analysis = useQuery({
    queryKey: ["feature-analysis", submitted?.analysisId],
    queryFn: () => client.getFeatureAnalysis(submitted!.analysisId),
    enabled: submitted !== null,
  });

  const submitAnalysis = useMutation({
    mutationFn: () =>
      client.createFeatureAnalysis({
        battery_id: batteryId,
        experiment_id: experimentId,
        analysis_mode: mode,
        target: "soc_reference_percent",
        candidate_features: candidates.split(",").map((s) => s.trim()).filter(Boolean),
      }),
    onSuccess: (result) => {
      const id = result.data.analysis_id;
      setSubmitted({ analysisId: id, reused: result.data.reuse_status === "REUSED" });
      setSearchParams({ analysis_id: id });
    },
    onError: (err) => setSubmitError(err),
  });

  return (
    <section aria-labelledby="fa-title">
      <h2 id="fa-title">特征分析 Feature Analysis</h2>

      <fieldset data-testid="mode-selector">
        <legend>分析模式（两种模式必须显式区分 — §20）</legend>
        <label>
          <input
            type="radio"
            name="fa-mode"
            checked={mode === "EXPLORATORY_FULL_DATA"}
            onChange={() => setMode("EXPLORATORY_FULL_DATA")}
          />
          探索性全数据分析 EXPLORATORY_FULL_DATA
        </label>
        <label>
          <input
            type="radio"
            name="fa-mode"
            checked={mode === "TRAIN_ONLY_ML_SAFE"}
            onChange={() => setMode("TRAIN_ONLY_ML_SAFE")}
          />
          ML 安全训练集分析 TRAIN_ONLY_ML_SAFE
        </label>
      </fieldset>

      {mode === "EXPLORATORY_FULL_DATA" ? (
        <p data-testid="exploratory-banner" role="note">
          ⚠️ Exploratory / not ML-safe for unbiased selection（探索性结果不能用于无偏特征选择）
        </p>
      ) : (
        <p data-testid="mlsafe-banner" role="note">
          训练组（TRAIN group）参与选择；HELD_OUT 组标签不参与 selection（§22）。
        </p>
      )}

      <label htmlFor="fa-candidates">候选特征（逗号分隔）：</label>
      <input
        id="fa-candidates"
        value={candidates}
        onChange={(e) => setCandidates(e.target.value)}
        size={50}
      />

      <button
        type="button"
        data-testid="run-analysis"
        onClick={() => {
          setSubmitError(null);
          submitAnalysis.mutate();
        }}
        disabled={submitAnalysis.isPending}
      >
        {submitAnalysis.isPending ? "提交中…" : "运行分析（POST /feature-analyses）"}
      </button>

      {submitError ? <ErrorBanner error={submitError} /> : null}

      {submitted ? (
        <div data-testid="analysis-result">
          <p>
            analysis_id: <code>{submitted.analysisId}</code>{" "}
            {submitted.reused ? <strong>（REUSED — 复用既有分析）</strong> : null}
          </p>
          {analysis.data ? (
            <p>状态: {analysis.data.data.status}</p>
          ) : analysis.error ? (
            <ErrorBanner error={analysis.error} />
          ) : (
            <p role="status">加载分析详情…</p>
          )}
        </div>
      ) : null}

      <h3>相关性表（渲染 API 提供的数据；不前端重算 — §24）</h3>
      <table data-testid="correlation-table">
        <caption>
          按 |Spearman| 排序展示（不自动命名 Best Feature — §23）
        </caption>
        <thead>
          <tr>
            <th>Feature</th>
            <th>Gate</th>
            <th>Pearson</th>
            <th>Spearman</th>
            <th>N</th>
            <th>Missing</th>
            <th>Scope</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td colSpan={8}>
              <small>
                分析产物明细由 /feature-analyses/{"{analysis_id}"} 提供；当前 API
                返回状态级信息时，此处不伪造数值。
              </small>
            </td>
          </tr>
        </tbody>
      </table>

      <h3>确认特征选择（§26）</h3>
      <p>
        <small>
          确认动作必须通过运行（run）的 UserActionRequired 合同提交；确认前不得自动 rebuild
          Dataset。请在「运行记录」页处理 pending action。
        </small>
      </p>
    </section>
  );
}

export function analysisErrorMessage(err: unknown): string | null {
  return err instanceof ApiError ? err.code : null;
}
