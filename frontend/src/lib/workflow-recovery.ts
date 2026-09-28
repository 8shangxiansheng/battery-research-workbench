export interface RecoveryAction {
  label: string;
  route: string;
}

/** Prefer the blocked step's concrete prerequisite over a later global action. */
export function recoveryActionFor(
  batteryId: string,
  experimentId: string,
  requiredAction?: string,
): RecoveryAction | null {
  const base = `/experiments/${batteryId}/${experimentId}`;
  switch (requiredAction) {
    case "BUILD_DATASET":
      return { label: "前往数据集步骤", route: `${base}/analysis?step=dataset` };
    case "CREATE_SPLIT":
    case "VALID_SPLIT_REQUIRED":
      return { label: "前往分组划分步骤", route: `${base}/analysis?step=selection` };
    case "TRAIN_MODELS":
    case "MODELS_MISSING":
      return { label: "前往模型页完成当前数据集评估", route: `${base}/models` };
    case "OPEN_REPORT":
      return { label: "查看科学报告", route: `${base}/report` };
    case "PROVIDE_SAMPLING_RATE":
    case "RESOLVE_PENDING_ACTION":
      return { label: "前往总览处理参数", route: `${base}/overview` };
    default:
      return null;
  }
}
