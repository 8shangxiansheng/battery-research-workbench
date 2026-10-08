import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { createE2EDataSandbox } from "./helpers/e2e-data-sandbox";

const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe("E2E data sandbox", () => {
  it("copies raw and processed inputs and keeps writes out of the source tree", () => {
    const repoRoot = mkdtempSync(join(tmpdir(), "brw-e2e-source-"));
    roots.push(repoRoot);
    mkdirSync(join(repoRoot, "data", "raw"), { recursive: true });
    mkdirSync(join(repoRoot, "data", "processed"), { recursive: true });
    writeFileSync(join(repoRoot, "data", "raw", "source.bin"), "raw");
    writeFileSync(join(repoRoot, "data", "processed", "artifact.json"), "original");

    const sandbox = createE2EDataSandbox(repoRoot);
    roots.push(sandbox.root);
    writeFileSync(join(sandbox.env.BRW_PROCESSED_ROOT!, "artifact.json"), "test write");

    expect(readFileSync(join(repoRoot, "data", "processed", "artifact.json"), "utf8")).toBe(
      "original",
    );
    expect(readFileSync(join(sandbox.env.BRW_RAW_ROOT!, "source.bin"), "utf8")).toBe("raw");
    expect(sandbox.env.BRW_RUNS_ROOT).toBe(join(sandbox.root, "runs"));

    sandbox.dispose();
    expect(existsSync(sandbox.root)).toBe(false);
    roots.splice(roots.indexOf(sandbox.root), 1);
  });
});
