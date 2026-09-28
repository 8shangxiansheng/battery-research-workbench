import { describe, expect, it } from "vitest";
import type { ResultRecord } from "../src/api/client";
import { partitionResultsByDataset } from "../src/lib/result-freshness";

const result = (dataset_id: string | null): ResultRecord => ({ dataset_id } as ResultRecord);

describe("model result freshness", () => {
  it("separates current-dataset evidence from prior and unscoped results", () => {
    const partition = partitionResultsByDataset([result("DS::current"), result("DS::old"), result(null)], "DS::current");
    expect(partition.current.map(item => item.dataset_id)).toEqual(["DS::current"]);
    expect(partition.historical.map(item => item.dataset_id)).toEqual(["DS::old", null]);
  });

  it("does not treat any result as current until a committed dataset id is available", () => {
    expect(partitionResultsByDataset([result("DS::old")], null)).toEqual({ current: [], historical: [result("DS::old")] });
  });
});
