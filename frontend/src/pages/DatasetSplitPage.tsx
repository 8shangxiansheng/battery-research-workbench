/**
 * 数据集与划分（§27-29）。
 * deterministic create（POST /datasets /splits）→ REUSED；
 * 分组 TRAIN/HELD_OUT；不可行 3-way 显示合法方案，禁止 random row fallback（§29/§36）。
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { client } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";

export function DatasetSplitPage() {
  const { batteryId = "", experimentId = "" } = useParams();
  const [selectedFeatures, setSelectedFeatures] = useState<string[]>([]);
  const [datasetResult, setDatasetResult] = useState<Record<string, unknown> | null>(null);
  const [splitResult, setSplitResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<unknown>(null);

  const features = useQuery({
    queryKey: ["features", batteryId, experimentId],
    queryFn: () => client.listFeatures(batteryId, experimentId),
  });
  const experiments = useQuery({
    queryKey: ["experiment", batteryId, experimentId],
    queryFn: () => client.getExperiment(batteryId, experimentId),
  });

  const createDataset = useMutation({
    mutationFn: () =>
      client.createDataset({
        battery_id: batteryId,
        experiment_id: experimentId,
        dataset_family: "SOC",
        selected_features: selectedFeatures,
      }),
    onSuccess: (r) => setDatasetResult(r.data),
    onError: (e) => setError(e),
  });
  const createSplit = useMutation({
    mutationFn: (datasetId: string) =>
      client.createSplit({
        battery_id: batteryId,
        experiment_id: experimentId,
        dataset_id: datasetId,
      }),
    onSuccess: (r) => setSplitResult(r.data),
    onError: (e) => setError(e),
  });

  const artifacts = experiments.data?.data.latest_canonical_artifacts ?? {};
  const datasetId = (datasetResult?.dataset_id as string) ?? artifacts.dataset_id ?? null;
  const availableFeatures = (features.data?.data.features ?? []).filter(
    (f) => f.availability === "AVAILABLE",
  );
  const unavailable = (features.data?.data.features ?? []).filter(
    (f) => f.availability !== "AVAILABLE",
  );

  return (
    <section aria-labelledby="ds-title">
      <h2 id="ds-title">数据集与划分 Dataset &amp; Split</h2>

      <h3>特征选择（显式选择 → 提交后构建）</h3>
      {features.isLoading ? (
        <p role="status">加载特征…</p>
      ) : features.error ? (
        <ErrorBanner error={features.error} />
      ) : (
        <fieldset data-testid="feature-picker">
          <legend>可用特征（blocked 特征不可选）</legend>
          {availableFeatures.map((f) => (
            <label key={f.feature_name} style={{ display: "block" }}>
              <input
                type="checkbox"
                checked={selectedFeatures.includes(f.feature_name)}
                onChange={(e) =>
                  setSelectedFeatures((prev) =>
                    e.target.checked
                      ? [...prev, f.feature_name]
                      : prev.filter((x) => x !== f.feature_name),
                  )
                }
              />
              <code>{f.feature_name}</code>
            </label>
          ))}
          <p>
            <small>不可用（不展示为 predictor，§33）: {unavailable.map((f) => f.feature_name).join(", ") || "无"}</small>
          </p>
        </fieldset>
      )}

      <button
        type="button"
        data-testid="create-dataset"
        disabled={createDataset.isPending}
        onClick={() => {
          setError(null);
          createDataset.mutate();
        }}
      >
        {createDataset.isPending ? "提交中…" : "构建数据集（POST /datasets）"}
      </button>

      {datasetResult ? (
        <div data-testid="dataset-result">
          <p>
            dataset_id: <code>{String(datasetResult.dataset_id)}</code> —{" "}
            <strong>{String(datasetResult.status)}</strong>
            {datasetResult.status === "REUSED" ? "（幂等复用，同 spec 同 ID）" : null}
          </p>
          <p>
            <small>limitations: {JSON.stringify(datasetResult.limitations)}</small>
          </p>
          {datasetId ? (
            <button
              type="button"
              data-testid="create-split"
              disabled={createSplit.isPending}
              onClick={() => {
                setError(null);
                createSplit.mutate(datasetId);
              }}
            >
              {createSplit.isPending ? "提交中…" : "创建划分（POST /splits）"}
            </button>
          ) : null}
        </div>
      ) : null}

      {splitResult ? (
        <div data-testid="split-result">
          <p>
            split_id: <code>{String(splitResult.split_id)}</code> —{" "}
            <strong>{String(splitResult.status)}</strong>
          </p>
          <p>
            strategy: {String(splitResult.group_column === "cycle_group_id" ? "LEAVE_ONE_GROUP_OUT" : String(splitResult.strategy ?? "LEAVE_ONE_GROUP_OUT"))} ·
            group_column: <code>{String(splitResult.group_column)}</code> · require_roles:{" "}
            <strong data-testid="require-roles">{JSON.stringify(splitResult.require_roles)}</strong>
          </p>
          <p>
            <small>
              TRAIN / HELD_OUT 分组评估（leave-one-cycle-out）；HELD_OUT 不参与
              selection/fit；2 独立组不支持 3-way，禁止 random row fallback（§29）。
            </small>
          </p>
        </div>
      ) : null}

      {error ? <ErrorBanner error={error} /> : null}
    </section>
  );
}
