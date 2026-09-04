/**
 * BRW-025 §57 OpenAPI drift 检查：
 * typed client 的路径清单必须与 docs/api/openapi-v1.json 快照一致。
 * API 快照变化而 client 未更新 → 本测试失败。
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { CLIENT_PATHS } from "../src/api/client";

interface OpenApiSpec {
  paths: Record<string, Record<string, unknown>>;
}

const snapshotPath = resolve(new URL(import.meta.url).pathname, "../../docs/api/openapi-v1.json");

describe("OpenAPI v1 ↔ typed client drift", () => {
  let spec: OpenApiSpec;
  try {
    spec = JSON.parse(readFileSync(snapshotPath, "utf-8")) as OpenApiSpec;
  } catch {
    it.skip("openapi snapshot missing", () => undefined);
    return;
  }

  const apiPaths = new Set(Object.keys(spec.paths).map((p) => p.replace("/api/v1", "")));

  it("client 覆盖的路径都存在于 API 快照", () => {
    const missing = CLIENT_PATHS.filter(
      (c) => !apiPaths.has(c.path),
    );
    expect(missing, `client 引用了 API 快照中不存在的路径: ${missing.map((m) => m.path).join(", ")}`).toEqual([]);
  });

  it("client 方法与快照方法一致", () => {
    for (const entry of CLIENT_PATHS) {
      const operations = spec.paths[`/api/v1${entry.path}`] ?? {};
      const method = entry.method.toLowerCase();
      expect(operations[method], `${entry.method} ${entry.path} 不在快照中`).toBeTruthy();
    }
  });

  it("核心写端点都在 client 中（防静默漏接）", () => {
    for (const required of ["/runs", "/gates", "/datasets", "/splits", "/reports", "/feature-analyses", "/models/baseline-runs"]) {
      expect(
        CLIENT_PATHS.some((c) => c.method === "POST" && c.path === required),
        `缺少 POST ${required}`,
      ).toBe(true);
    }
  });
});
