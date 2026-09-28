import type { ResultRecord } from "../api/client";

export interface ResultFreshnessPartition {
  current: ResultRecord[];
  historical: ResultRecord[];
}

/** Only metrics tied to the committed dataset may support the current model conclusion. */
export function partitionResultsByDataset(
  results: readonly ResultRecord[],
  currentDatasetId: string | null,
): ResultFreshnessPartition {
  if (!currentDatasetId) return { current: [], historical: [...results] };
  return {
    current: results.filter(result => result.dataset_id === currentDatasetId),
    historical: results.filter(result => result.dataset_id !== currentDatasetId),
  };
}
