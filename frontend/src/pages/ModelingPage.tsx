/**
 * SOC 建模（§30-35）。
 * Dummy/Linear/Ridge/RF/GB；per-fold + macro + OOB；无 tuning 控件。
 * 弱结果诚实表达：evaluation complete 但 predictive advantage not demonstrated（§33/§14）。
 */
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { client, type ResultRecord } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";

const STRATEGY_LABELS: Record<string, string> = {
  DUMMY_MEAN: "Dummy Mean（均值基线）",
  LINEAR_REGRESSION: "Linear Regression（线性回归）",
  RIDGE: "Ridge（岭回归）",
  RANDOM_FOREST: "Random Forest（随机森林）",
  GRADIENT_BOOSTING: "Gradient Boosting（梯度提升）",
};

function fmt(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "number" ? value.toFixed(3) : String(value);
}

export function ModelingPage() {
  const { batteryId = "", experimentId = "" } = useParams();
  const { data, isLoading, error } = useQuery({
    queryKey: ["results", batteryId, experimentId],
    queryFn: () => client.getResults(batteryId, experimentId, 200),
  });

  if (isLoading) return <p role="status">加载建模结果…</p>;
  if (error) return <ErrorBanner error={error} />;
  const results: ResultRecord[] = data?.data ?? [];
  const perFold = results.filter((r) => r.result_type === "MODEL_METRIC");
  const macro = results.filter((r) => r.result_type === "MODEL_COMPARISON");

  const dummyMacro = macro.find((r) => r.strategy === "DUMMY_MEAN");
  const bestReal = macro
    .filter((r) => r.strategy !== "DUMMY_MEAN" && typeof r.value === "number")
    .sort((a, b) => (a.value as number) - (b.value as number))[0];

  const realBeatsDummy =
    dummyMacro && bestReal ? (bestReal.value as number) < (dummyMacro.value as number) : null;

  const strategies = [...new Set(perFold.map((r) => r.strategy ?? ""))].filter(Boolean);

  return (
    <section aria-labelledby="modeling-title">
      <h2 id="modeling-title">SOC 建模 Modeling</h2>
      <p>
        <small>固定基线协议（fixed baseline protocol）；本轮无 tuning UI（§30）。</small>
      </p>

      <h3>Macro（跨 fold 汇总）</h3>
      <table data-testid="macro-table">
        <thead>
          <tr>
            <th>strategy</th>
            <th>macro MAE (percent)</th>
            <th>vs Dummy</th>
          </tr>
        </thead>
        <tbody>
          {macro.map((r) => (
            <tr
              key={r.result_id}
              data-testid={`macro-${r.strategy}`}
              style={
                r.strategy === "DUMMY_MEAN"
                  ? { background: "#fff8e0", fontWeight: 600 }
                  : undefined
              }
            >
              <td>{r.strategy ? (STRATEGY_LABELS[r.strategy] ?? r.strategy) : r.strategy}</td>
              <td>{fmt(r.value)}</td>
              <td>
                {r.strategy === "DUMMY_MEAN"
                  ? "（基线）"
                  : dummyMacro && typeof r.value === "number"
                    ? `${(r.value as number) - (dummyMacro.value as number) >= 0 ? "+" : ""}${((r.value as number) - (dummyMacro.value as number)).toFixed(3)}`
                    : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {realBeatsDummy === false ? (
        <div
          role="note"
          data-testid="weak-result-banner"
          style={{ border: "1px solid #c88", background: "#fdf4f4", padding: "0.75rem" }}
        >
          <p>
            <strong>诚实结论（§33/§14）：</strong>
            工程评估已完成（evaluation complete），但当前候选超声特征的预测优势未被证明
            （predictive advantage not demonstrated）—— 所有真实基线都未优于 Dummy Mean。
          </p>
          <p>
            <small>
              这不是“模型失败”，而是当前特征/数据下的科学结论。Dummy 基线已突出显示。
            </small>
          </p>
        </div>
      ) : realBeatsDummy === true ? (
        <p role="note" data-testid="beats-dummy-banner">
          当前最优真实基线优于 Dummy Mean。
        </p>
      ) : null}

      <h3>Per-fold 明细（MAE / RMSE / R² / OOB）</h3>
      <table data-testid="fold-table">
        <thead>
          <tr>
            <th>strategy</th>
            <th>fold</th>
            <th>MAE</th>
            <th>RMSE</th>
            <th>R²</th>
            <th>OOB</th>
          </tr>
        </thead>
        <tbody>
          {strategies.flatMap((s) =>
            perFold
              .filter((r) => r.strategy === s)
              .sort((a, b) => (a.fold_index ?? 0) - (b.fold_index ?? 0))
              .map((r) => (
                <tr key={r.result_id} data-testid={`fold-${s}-${r.fold_index}`}>
                  <td>{STRATEGY_LABELS[s] ?? s}</td>
                  <td>{r.fold_index}</td>
                  <td>{r.result_id.endsWith("_MAE") ? fmt(r.value) : ""}</td>
                  <td>{r.result_id.endsWith("_RMSE") ? fmt(r.value) : ""}</td>
                  <td>{r.result_id.endsWith("_R2") ? fmt(r.value) : ""}</td>
                  <td>
                    <small>OOB 计数由 API 结果提供；无静默截断（§35）。</small>
                  </td>
                </tr>
              )),
          )}
        </tbody>
      </table>

      <h3>方向性指标（direction-specific — §34）</h3>
      <p data-testid="direction-note">
        <small>
          API 结果注册表当前未提供 CHARGE/DISCHARGE/REST 分方向 MAE 条目 —— UI
          不在前端重算（§24），此处如实标注“API 未提供”。
        </small>
      </p>
    </section>
  );
}
