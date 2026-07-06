import type { ComparisonSummary } from "../api";

export default function MetricsCards({ summary }: { summary: ComparisonSummary }) {
  const cards = [
    { label: "Symbols evaluated", value: summary.n_symbols.toString() },
    { label: "Mean ARIMA RMSE", value: summary.mean_arima_rmse.toFixed(2) },
    { label: "Mean XGBoost RMSE", value: summary.mean_xgb_rmse.toFixed(2) },
    { label: "RMSE improvement", value: `${summary.pct_rmse_improvement.toFixed(1)}%` },
    { label: "XGBoost wins", value: `${summary.xgb_wins}/${summary.n_symbols}` },
    {
      label: "Wilcoxon p-value",
      value: summary.p_value < 0.001 ? summary.p_value.toExponential(2) : summary.p_value.toFixed(4),
    },
  ];

  return (
    <div className="metrics-grid">
      {cards.map((c) => (
        <div className="metric-card" key={c.label}>
          <p className="metric-value">{c.value}</p>
          <p className="metric-label">{c.label}</p>
        </div>
      ))}
      <div className="metric-card metric-card--wide">
        <p className="metric-label">
          {summary.significant_at_0_05 ? "✅ Statistically significant" : "⚠️ Not significant"} at
          α = 0.05 (paired Wilcoxon signed-rank test across {summary.n_symbols} symbols)
        </p>
      </div>
    </div>
  );
}
