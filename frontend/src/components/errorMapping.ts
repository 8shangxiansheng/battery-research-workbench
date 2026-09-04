/**
 * BRW-025 错误→UX 映射（§55）。
 * SCIENTIFIC_ACTION_REQUIRED → 行动面板
 * SCIENTIFIC_READINESS_BLOCKED → 就绪面板
 * ARTIFACT_NOT_AVAILABLE → 可用性面板
 * VALIDATION_ERROR → 字段反馈
 * INTERNAL_ERROR → 友好错误 + request_id（不显示 traceback）
 */
import { ApiError } from "../api/client";

export type ErrorPanelKind =
  | "scientific-action"
  | "readiness-blocked"
  | "artifact-unavailable"
  | "validation"
  | "integrity"
  | "internal";

export function classifyError(err: unknown): ErrorPanelKind {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "SCIENTIFIC_ACTION_REQUIRED":
        return "scientific-action";
      case "SCIENTIFIC_READINESS_BLOCKED":
        return "readiness-blocked";
      case "ARTIFACT_NOT_AVAILABLE":
        return "artifact-unavailable";
      case "VALIDATION_ERROR":
        return "validation";
      case "INTEGRITY_ERROR":
        return "integrity";
      default:
        return "internal";
    }
  }
  return "internal";
}

export const ERROR_PANEL_TEXT: Record<ErrorPanelKind, { title: string; hint: string }> = {
  "scientific-action": {
    title: "需要科学操作（Scientific Action Required）",
    hint: "需要你提供科学参数后才能继续。请填写下方表单，不会自动代填。",
  },
  "readiness-blocked": {
    title: "科学就绪状态受阻（Readiness Blocked）",
    hint: "这不是软件故障：当前科学状态不允许此操作。",
  },
  "artifact-unavailable": {
    title: "产物不可用（Artifact Not Available）",
    hint: "当前环境无法访问该产物。可查看已有证据，但必须保持证据标签。",
  },
  validation: {
    title: "输入无效（Validation Error）",
    hint: "请检查表单字段。",
  },
  integrity: {
    title: "完整性错误（Integrity Error）",
    hint: "检测到数据完整性问题，请勿继续操作并联系维护者。",
  },
  internal: {
    title: "服务器内部错误（Internal Error）",
    hint: "发生了意外错误。可凭 request_id 排查日志；详情不会显示在此处。",
  },
};

export function errorRequestId(err: unknown): string | null {
  return err instanceof ApiError ? err.requestId : null;
}
