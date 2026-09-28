import { describe, expect, it } from "vitest";
import { recoveryActionFor } from "../src/lib/workflow-recovery";

describe("workflow recovery routes", () => {
  it("routes each prerequisite to its actual owning workflow step", () => {
    expect(recoveryActionFor("CELL_001", "EXP_001", "CREATE_SPLIT")).toEqual({
      label: "前往分组划分步骤", route: "/experiments/CELL_001/EXP_001/analysis?step=selection",
    });
    expect(recoveryActionFor("CELL_001", "EXP_001", "TRAIN_MODELS")).toEqual({
      label: "前往模型页完成当前数据集评估", route: "/experiments/CELL_001/EXP_001/models",
    });
    expect(recoveryActionFor("CELL_001", "EXP_001", "BUILD_DATASET")?.route)
      .toBe("/experiments/CELL_001/EXP_001/analysis?step=dataset");
  });

  it("does not invent a recovery action for unknown backend action ids", () => {
    expect(recoveryActionFor("CELL_001", "EXP_001", "UNKNOWN_ACTION")).toBeNull();
  });
});
