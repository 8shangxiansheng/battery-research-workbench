import type { ExperimentDataAsset, FeatureLabelPreviewRow } from "../api/client";

/** Resolve the row's electrical asset via manifest IDs, never by a guessed filename. */
export function electricalAssetForRow(
  row: Pick<FeatureLabelPreviewRow, "electrical_asset_id">,
  batteryId: string,
  experimentId: string,
  assets: readonly ExperimentDataAsset[],
): ExperimentDataAsset | null {
  if (!row.electrical_asset_id) return null;
  return assets.find(asset =>
    asset.asset_id === row.electrical_asset_id
    && asset.experiment_id === experimentId
    && (!asset.battery_id || asset.battery_id === batteryId)
    && asset.modality.toLowerCase() === "electrical",
  ) ?? null;
}
