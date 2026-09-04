/** 统一错误面板（§55）：分类渲染，不显示 traceback。 */
import type { ReactElement } from "react";
import { classifyError, ERROR_PANEL_TEXT, errorRequestId } from "./errorMapping";

export function ErrorBanner({ error }: { error: unknown }): ReactElement {
  const kind = classifyError(error);
  const text = ERROR_PANEL_TEXT[kind];
  const requestId = errorRequestId(error);
  return (
    <div
      role="alert"
      data-testid={`error-panel-${kind}`}
      style={{
        border: "1px solid #b53",
        background: "#fdf3f0",
        padding: "0.75rem 1rem",
        borderRadius: 4,
      }}
    >
      <p>
        <strong>{text.title}</strong>
      </p>
      <p>{text.hint}</p>
      {requestId ? (
        <p>
          <small>request_id: <code>{requestId}</code></small>
        </p>
      ) : null}
    </div>
  );
}
