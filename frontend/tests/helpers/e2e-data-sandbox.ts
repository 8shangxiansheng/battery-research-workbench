import { cpSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

export interface E2EDataSandbox {
  env: NodeJS.ProcessEnv;
  root: string;
  dispose: () => void;
}

/** Copy the current experiment data so API E2E writes cannot mutate repo artifacts. */
export function createE2EDataSandbox(repoRoot: string): E2EDataSandbox {
  const root = mkdtempSync(join(tmpdir(), "brw-e2e-data-"));
  const rawRoot = join(root, "raw");
  const processedRoot = join(root, "processed");
  const runsRoot = join(root, "runs");

  try {
    cpSync(join(repoRoot, "data", "raw"), rawRoot, { recursive: true });
    cpSync(join(repoRoot, "data", "processed"), processedRoot, { recursive: true });
    mkdirSync(runsRoot, { recursive: true });
  } catch (error) {
    rmSync(root, { recursive: true, force: true });
    throw error;
  }

  return {
    root,
    env: {
      ...process.env,
      BRW_RAW_ROOT: rawRoot,
      BRW_PROCESSED_ROOT: processedRoot,
      BRW_RUNS_ROOT: runsRoot,
    },
    dispose: () => rmSync(root, { recursive: true, force: true }),
  };
}
