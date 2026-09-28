import { describe, expect, it } from "vitest";
import { electricalAssetForRow } from "../src/lib/asset-provenance";
import type { ExperimentDataAsset } from "../src/api/client";

const asset = (overrides: Partial<ExperimentDataAsset> = {}): ExperimentDataAsset => ({
  asset_id: "E001", battery_id: "CELL_001", experiment_id: "EXP_001", modality: "electrical",
  relative_path: "batteries/CELL_001/EXP_001/electrical/cell.xlsx", file_start_time: null,
  file_end_time: null, parser_name: "neware", parser_version: "1.0", ...overrides,
});

describe("raw DataAsset provenance resolution", () => {
  it("uses the row's electrical asset id and experiment scope to resolve manifest path", () => {
    expect(electricalAssetForRow({ electrical_asset_id: "E001" }, "CELL_001", "EXP_001", [asset()])?.relative_path)
      .toBe("batteries/CELL_001/EXP_001/electrical/cell.xlsx");
  });

  it("rejects other battery, modality, experiment, and missing asset IDs", () => {
    expect(electricalAssetForRow({ electrical_asset_id: "E001" }, "CELL_002", "EXP_001", [asset()])).toBeNull();
    expect(electricalAssetForRow({ electrical_asset_id: "E001" }, "CELL_001", "EXP_002", [asset()])).toBeNull();
    expect(electricalAssetForRow({ electrical_asset_id: "E001" }, "CELL_001", "EXP_001", [asset({ modality: "ultrasound" })])).toBeNull();
    expect(electricalAssetForRow({ electrical_asset_id: null }, "CELL_001", "EXP_001", [asset()])).toBeNull();
  });
});
