/**
 * 数据集与划分（§27-29）。
 * Dataset / Split 均通过 orchestrator run 物化；
 * 分组 TRAIN/HELD_OUT；不可行方案展示恢复路径，禁止 random row fallback（§29/§36）。
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { client } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";
import { startGroupedSplitRun } from "../lib/grouped-split";

export function DatasetSplitPage() {
  const { batteryId = "", experimentId = "" } = useParams();
  const queryClient = useQueryClient();
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
    mutationFn: async () => {
      const r = await client.startRun({
        profile: "BUILD_DATASET",
        battery_id: batteryId,
        experiment_id: experimentId,
        target: "soc_reference_percent",
        features: { selected_features: selectedFeatures },
      });
      const payload = r.data as Record<string, unknown>;
      const artifacts = Array.isArray(payload.final_artifacts) ? payload.final_artifacts as Record<string, unknown>[] : [];
      const dataset = artifacts.find((item) => item.artifact_type === "DATASET");
      if (payload.status !== "SUCCEEDED" || !dataset?.artifact_id) {
        throw new Error(`Dataset run 未完成（${String(payload.status ?? "UNKNOWN")}）`);
      }
      return {
        dataset_id: dataset.artifact_id,
        status: dataset.status ?? "MATERIALIZED",
        run_status: payload.status,
        run_id: payload.run_id,
      };
    },
    onSuccess: (r) => {
      setDatasetResult(r);
      setSplitResult(null);
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["workflow-context", batteryId, experimentId] });
      void queryClient.invalidateQueries({ queryKey: ["experiment", batteryId, experimentId] });
      void queryClient.invalidateQueries({ queryKey: ["datasets"] });
    },
    onError: (e) => setError(e),
  });
  const createSplit = useMutation({
    mutationFn: async () => {
      const { response, split, dataset, readinessStatus } = await startGroupedSplitRun(batteryId, experimentId, selectedFeatures);
      const payload = response.data as Record<string, unknown>;
      return {
        split_id: split.artifact_id,
        dataset_id: dataset?.artifact_id,
        status: readinessStatus ?? payload.status,
        strategy: "LEAVE_ONE_GROUP_OUT",
        group_column: "cycle_group_id",
        require_roles: ["TRAIN", "HELD_OUT"],
        run_id: payload.run_id,
      };
    },
    onSuccess: (r) => {
      setSplitResult(r);
      if (r.dataset_id) {
        setDatasetResult((previous) => ({ ...previous, dataset_id: r.dataset_id }));
      }
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["workflow-context", batteryId, experimentId] });
      void queryClient.invalidateQueries({ queryKey: ["splits", batteryId, experimentId] });
      void queryClient.invalidateQueries({ queryKey: ["experiment", batteryId, experimentId] });
    },
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
        disabled={createDataset.isPending || !selectedFeatures.length}
        onClick={() => {
          setError(null);
          createDataset.mutate();
        }}
      >
        {createDataset.isPending ? "构建运行中…" : "构建 Dataset / Build Dataset"}
      </button>

      {datasetResult ? (
        <div data-testid="dataset-result">
          <p>
            dataset_id: <code>{String(datasetResult.dataset_id)}</code> —{" "}
            <strong>{String(datasetResult.status)}</strong>
            {datasetResult.run_id ? <small> · run <code>{String(datasetResult.run_id)}</code></small> : null}
          </p>
          {datasetId ? (
            <button
              type="button"
              data-testid="create-split"
              disabled={createSplit.isPending}
              onClick={() => {
                setError(null);
                createSplit.mutate();
              }}
            >
              {createSplit.isPending ? "划分运行中…" : "构建分组划分 / Build grouped split"}
            </button>
          ) : null}
        </div>
      ) : null}

      {splitResult ? (
        <div data-testid="split-result">
          <p>
            split_id: <code>{String(splitResult.split_id)}</code> —{" "}
            <strong>{String(splitResult.status)}</strong>
            {splitResult.run_id ? <small> · run <code>{String(splitResult.run_id)}</code></small> : null}
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
      {error ? <p className="mt-2 text-sm"><Link className="underline" to="/runs">查看运行记录或处理待办用户动作</Link></p> : null}
    </section>
  );
}
