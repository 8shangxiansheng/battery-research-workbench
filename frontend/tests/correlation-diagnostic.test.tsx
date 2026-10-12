import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CorrelationDiagnosticPlot } from "../src/components/workbench/CorrelationDiagnosticPlot";

vi.mock("react-plotly.js/factory", () => ({
  default: () => (props: { data: unknown[] }) => (
    <div data-testid="plotly-mock" data-traces={props.data.length} />
  ),
}));

describe("Battery 分层关系诊断图", () => {
  it("renders backend event samples and all-data battery means without recomputation", () => {
    render(<CorrelationDiagnosticPlot diagnostic={{
      policy: "BATTERY_STRATIFIED_SCATTER_DIAGNOSTIC_V1",
      feature_code: "SWA",
      target_id: "reference_soc_percent",
      n_input: 22,
      n_valid: 20,
      missing_feature_count: 1,
      missing_state_count: 0,
      excluded_ineligible_count: 1,
      sampled: true,
      max_points: 6,
      random_seed: 21,
      group_coverage_complete: true,
      points: [{
        battery_id: "CELL_A", cycle: 1, state: "charge",
        feature_value: 4, target_value: 14,
      }],
      battery_means: [{
        battery_id: "CELL_A", n_valid: 10,
        feature_mean: 4.5, target_mean: 14.5,
      }],
      limitation: "Exploratory visualization only.",
    }} />);

    expect(screen.getByTestId("correlation-diagnostic-plot")).toHaveTextContent("显示 1/20 个有效配对");
    expect(screen.getByTestId("correlation-diagnostic-plot")).toHaveTextContent("全部有效事件计算");
    expect(screen.getByTestId("plotly-mock")).toHaveAttribute("data-traces", "2");
  });
});
