import { client } from "../api/client";

export function groupedSplitRunRequest(
  batteryId: string,
  experimentId: string,
  selectedFeatures: string[],
  strategy = "LEAVE_ONE_GROUP_OUT",
) {
  return {
    profile: "EVALUATION_SPLIT",
    battery_id: batteryId,
    experiment_id: experimentId,
    target: "soc_reference_percent",
    features: { selected_features: [...selectedFeatures] },
    split: {
      strategy,
      split_unit: "CYCLE",
      group_column: "cycle_group_id",
    },
  };
}

export async function startGroupedSplitRun(
  batteryId: string,
  experimentId: string,
  selectedFeatures: string[],
  strategy = "LEAVE_ONE_GROUP_OUT",
) {
  const response = await client.startRun(
    groupedSplitRunRequest(batteryId, experimentId, selectedFeatures, strategy),
  );
  const run = response.data as Record<string, unknown>;
  const artifacts = Array.isArray(run.final_artifacts)
    ? (run.final_artifacts as Record<string, unknown>[])
    : [];
  const nodes = Array.isArray(run.nodes) ? (run.nodes as Record<string, unknown>[]) : [];
  const splitNode = nodes.find((item) => item.node_id === "SPLIT");
  const metrics = (splitNode?.metrics ?? {}) as Record<string, unknown>;
  const split = artifacts.find((item) => item.artifact_type === "SPLIT");
  const dataset = artifacts.find((item) => item.artifact_type === "DATASET");
  if (run.status !== "SUCCEEDED" || !split?.artifact_id) {
    throw new Error(
      `Split run ${String(run.run_id ?? "未生成 RUN ID")} 状态为 ${String(run.status ?? "UNKNOWN")}；请到 Runs 检查用户动作或失败原因。`,
    );
  }
  return { response, split, dataset, readinessStatus: metrics.readiness };
}
