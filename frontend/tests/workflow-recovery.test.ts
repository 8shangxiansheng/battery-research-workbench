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
    expect(recoveryActionFor("CELL_001", "EXP_001", "REPARSE_SOURCE_ASSETS_AND_REVIEW_LINEAGE")).toEqual({
      label: "重新解析并复核来源链", route: "/experiments/CELL_001/EXP_001/runs",
    });
    expect(recoveryActionFor("CELL_001", "EXP_001", "REBUILD_TIME_ANCHORS_AND_DOWNSTREAM_ALIGNMENT")).toEqual({
      label: "重建时间基准与同步链", route: "/experiments/CELL_001/EXP_001/runs",
    });
    expect(recoveryActionFor("CELL_001", "EXP_001", "REBUILD_MEASUREMENT_EVENTS_AND_LABELS_FROM_VERIFIED_INPUTS")).toEqual({
      label: "重建声电事件与标签", route: "/experiments/CELL_001/EXP_001/runs",
    });
  });

  it("does not invent a recovery action for unknown backend action ids", () => {
    expect(recoveryActionFor("CELL_001", "EXP_001", "UNKNOWN_ACTION")).toBeNull();
  });
});
