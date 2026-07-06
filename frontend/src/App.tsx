import { useEffect, useState } from "react";
import { api, ComparisonSummary, ForecastSeries, SymbolMetrics } from "./api";
import MetricsCards from "./components/MetricsCards";
import SymbolChart from "./components/SymbolChart";
import StatsTable from "./components/StatsTable";

export default function App() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [summary, setSummary] = useState<ComparisonSummary | null>(null);
  const [symbolMetrics, setSymbolMetrics] = useState<SymbolMetrics[]>([]);
  const [forecast, setForecast] = useState<ForecastSeries | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.symbols(), api.metrics(), api.symbolMetrics()])
      .then(([syms, sum, sm]) => {
        setSymbols(syms);
        setSummary(sum);
        setSymbolMetrics(sm);
        setSelected(syms.includes("AAPL") ? "AAPL" : syms[0]);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    api.forecast(selected).then(setForecast).catch((e) => setError(e.message));
  }, [selected]);

  if (error) {
    return (
      <div className="app-shell">
        <p className="error">
          Couldn't reach the API ({error}). Is the backend running and{" "}
          <code>VITE_API_BASE_URL</code> set correctly?
        </p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header>
        <h1>EquiSight</h1>
        <p className="subtitle">
          ARIMA vs. gradient-boosted (XGBoost) forecasting, head-to-head across{" "}
          {summary?.n_symbols ?? "…"} equities — 5 years of daily price history,
          walk-forward validated.
        </p>
      </header>

      {summary && <MetricsCards summary={summary} />}

      <section>
        <div className="section-header">
          <h2>Actual vs. forecast</h2>
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        {forecast && <SymbolChart data={forecast} />}
      </section>

      <section>
        <h2>Per-symbol statistical tests</h2>
        <StatsTable rows={symbolMetrics} />
      </section>

      <footer>
        <a href="https://github.com/VedaantAgrawal/EquiSight" target="_blank" rel="noopener">
          Source on GitHub
        </a>
      </footer>
    </div>
  );
}
