import type { StatusBlock, WorkspaceSummary } from "../api/client";

export function overviewNextStep(status?: StatusBlock, workspace?: WorkspaceSummary, hasModels = false) {
  if (!status || !workspace) return { kind: "unknown", label: "等待就绪检查", route: "" };
  if (!status.synchronization?.validated_sync || !["AVAILABLE", "READY"].includes(status.tof?.status)) {
    return { kind: "resolve", label: "完善前置参数", route: "" };
  }
  if (hasModels) return { kind: "navigate", label: "复核模型结果", route: "models" };
  if (!workspace.gate_set_id) return { kind: "navigate", label: "检查波形并确认闸门", route: "waveform" };
  return { kind: "navigate", label: "配置特征分析", route: "analysis" };
}
