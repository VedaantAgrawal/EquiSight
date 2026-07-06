const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8010";

export interface ComparisonSummary {
  n_symbols: number;
  mean_arima_rmse: number;
  mean_xgb_rmse: number;
  pct_rmse_improvement: number;
  xgb_wins: number;
  wilcoxon_statistic: number;
  p_value: number;
  significant_at_0_05: boolean;
  updated_at: string;
}

export interface SymbolMetrics {
  symbol: string;
  arima_order: string;
  arima_rmse: number;
  xgb_rmse: number;
  adf_statistic: number | null;
  adf_p_value: number | null;
  adf_stationary: boolean | null;
  ljung_box_p_value: number | null;
  ljung_box_white_noise: boolean | null;
}

export interface ForecastSeries {
  symbol: string;
  dates: string[];
  actual: number[];
  arima_pred: number[];
  xgb_pred: number[];
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`Request to ${path} failed: ${res.status}`);
  }
  return res.json();
}

export const api = {
  symbols: () => getJSON<string[]>("/api/symbols"),
  metrics: () => getJSON<ComparisonSummary>("/api/metrics"),
  symbolMetrics: () => getJSON<SymbolMetrics[]>("/api/metrics/symbols"),
  forecast: (symbol: string) => getJSON<ForecastSeries>(`/api/forecast/${symbol}`),
};
