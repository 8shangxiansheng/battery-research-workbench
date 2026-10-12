import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";
import type { FeatureCorrelationsResponse } from "../../api/client";

const Plot = createPlotlyComponent(Plotly);
const COLORS = ["#256b62", "#bf7b32", "#5967a8", "#a34e61", "#40819a", "#7b6593"];

export function CorrelationDiagnosticPlot({
  diagnostic,
}: {
  diagnostic?: FeatureCorrelationsResponse["soc_diagnostic_scatter"];
}) {
  if (!diagnostic) return null;
  const batteries = diagnostic.battery_means.map((group) => group.battery_id);
  const eventTraces = batteries.map((batteryId, index) => {
    const points = diagnostic.points.filter((point) => point.battery_id === batteryId);
    return {
      x: points.map((point) => point.feature_value),
      y: points.map((point) => point.target_value),
      customdata: points.map((point) => [point.cycle, point.state]),
      type: "scatter" as const,
      mode: "markers" as const,
      name: `${batteryId} · events`,
      marker: { color: COLORS[index % COLORS.length], size: 5, opacity: 0.5 },
      hovertemplate: "Feature %{x:.3f}<br>Reference SOC %{y:.2f}%<br>Cycle %{customdata[0]} · %{customdata[1]}<extra></extra>",
    };
  });
  const meanTrace = {
    x: diagnostic.battery_means.map((group) => group.feature_mean),
    y: diagnostic.battery_means.map((group) => group.target_mean),
    text: diagnostic.battery_means.map((group) => group.battery_id),
    type: "scatter" as const,
    mode: "markers+text" as const,
    name: "Battery mean · all valid events",
    textposition: "top center" as const,
    marker: {
      color: diagnostic.battery_means.map((_, index) => COLORS[index % COLORS.length]),
      size: 13,
      symbol: "diamond",
      line: { color: "#172b36", width: 1 },
    },
    hovertemplate: "%{text}<br>Mean feature %{x:.3f}<br>Mean Reference SOC %{y:.2f}%<extra></extra>",
  };

  return (
    <figure className="panel mt-4 p-4" data-testid="correlation-diagnostic-plot">
      <figcaption>
        <h3 className="font-medium">Battery 分层关系诊断</h3>
        <p className="muted text-xs mt-1">
          {diagnostic.feature_code} × Reference SOC；圆点为事件，菱形为使用全部有效事件计算的 Battery 均值。
          {diagnostic.sampled ? ` 事件点确定性分层抽样，显示 ${diagnostic.points.length}/${diagnostic.n_valid} 个有效配对。` : " 显示全部有效事件。"}
        </p>
        {!diagnostic.group_coverage_complete && (
          <p role="status" className="notice mt-2 text-xs">Battery 数超过事件点显示上限；均值点仍覆盖全部 Battery。</p>
        )}
      </figcaption>
      <div aria-label="Battery 分层关系散点图">
        <Plot
          data={[...eventTraces, meanTrace]}
          layout={{
            autosize: true,
            height: 340,
            margin: { l: 58, r: 18, t: 18, b: 60 },
            paper_bgcolor: "#ffffff",
            plot_bgcolor: "#ffffff",
            xaxis: { title: { text: `${diagnostic.feature_code} (a.u.)` }, automargin: true, zeroline: false },
            yaxis: { title: { text: "Reference SOC (%)" }, automargin: true, zeroline: false },
            legend: { orientation: "h", y: -0.25 },
            hovermode: "closest",
          }}
          config={{ displayModeBar: false, responsive: true }}
          useResizeHandler
          style={{ width: "100%", height: "340px" }}
        />
      </div>
      <p className="muted text-xs mt-1">
        {diagnostic.limitation} 缺失 feature {diagnostic.missing_feature_count}、缺失 state {diagnostic.missing_state_count}、同步排除 {diagnostic.excluded_ineligible_count} / 输入 {diagnostic.n_input}。
      </p>
    </figure>
  );
}
