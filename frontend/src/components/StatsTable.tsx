import type { SymbolMetrics } from "../api";

export default function StatsTable({ rows }: { rows: SymbolMetrics[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>ARIMA order</th>
            <th>ARIMA RMSE</th>
            <th>XGBoost RMSE</th>
            <th>Improvement</th>
            <th>ADF (stationary?)</th>
            <th>Ljung-Box (white noise?)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const improvement = ((r.arima_rmse - r.xgb_rmse) / r.arima_rmse) * 100;
            return (
              <tr key={r.symbol}>
                <td className="mono">{r.symbol}</td>
                <td className="mono">{r.arima_order}</td>
                <td>{r.arima_rmse.toFixed(2)}</td>
                <td>{r.xgb_rmse.toFixed(2)}</td>
                <td className={improvement >= 0 ? "positive" : "negative"}>
                  {improvement.toFixed(1)}%
                </td>
                <td>
                  {r.adf_stationary === null
                    ? "—"
                    : r.adf_stationary
                    ? "Stationary"
                    : "Non-stationary"}{" "}
                  <span className="dim">(p={r.adf_p_value?.toFixed(3)})</span>
                </td>
                <td>
                  {r.ljung_box_white_noise === null
                    ? "—"
                    : r.ljung_box_white_noise
                    ? "White noise"
                    : "Autocorrelated"}{" "}
                  <span className="dim">(p={r.ljung_box_p_value?.toFixed(3)})</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
