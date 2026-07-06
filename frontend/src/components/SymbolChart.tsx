import Plot from "react-plotly.js";
import type { ForecastSeries } from "../api";

export default function SymbolChart({ data }: { data: ForecastSeries }) {
  return (
    <Plot
      data={[
        {
          x: data.dates,
          y: data.actual,
          type: "scatter",
          mode: "lines",
          name: "Actual close",
          line: { color: "#e2e8f0", width: 2 },
        },
        {
          x: data.dates,
          y: data.arima_pred,
          type: "scatter",
          mode: "lines",
          name: "ARIMA forecast",
          line: { color: "#f97316", width: 1.5, dash: "dot" },
        },
        {
          x: data.dates,
          y: data.xgb_pred,
          type: "scatter",
          mode: "lines",
          name: "XGBoost forecast",
          line: { color: "#34d399", width: 1.5, dash: "dot" },
        },
      ]}
      layout={{
        autosize: true,
        height: 420,
        margin: { l: 50, r: 20, t: 20, b: 40 },
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        font: { color: "#cbd5e1" },
        xaxis: { gridcolor: "#1e293b" },
        yaxis: { gridcolor: "#1e293b", title: { text: "Price (USD)" } },
        legend: { orientation: "h", y: -0.15 },
      }}
      useResizeHandler
      style={{ width: "100%" }}
      config={{ displayModeBar: false, responsive: true }}
    />
  );
}
