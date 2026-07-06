"""
Loads the JSON results produced by run_pipeline.py into Postgres, so the
FastAPI backend can serve them without needing pandas/xgboost/statsmodels
as runtime dependencies.

Usage: DB_URL=postgresql://... python3 db_load.py
"""

import json
import os

import psycopg

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
DB_URL = os.environ["DB_URL"]


def load():
    with open(os.path.join(RESULTS_DIR, "comparison_summary.json")) as f:
        summary = json.load(f)
    with open(os.path.join(RESULTS_DIR, "per_symbol_summary.json")) as f:
        per_symbol = json.load(f)
    with open(os.path.join(RESULTS_DIR, "forecast_series.json")) as f:
        series = json.load(f)

    with open(os.path.join(os.path.dirname(__file__), "db_schema.sql")) as f:
        schema_sql = f.read()

    with psycopg.connect(DB_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)

            cur.execute(
                """
                INSERT INTO comparison_summary
                    (id, n_symbols, mean_arima_rmse, mean_xgb_rmse,
                     pct_rmse_improvement, xgb_wins, wilcoxon_statistic,
                     p_value, significant_at_0_05, updated_at)
                VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (id) DO UPDATE SET
                    n_symbols = EXCLUDED.n_symbols,
                    mean_arima_rmse = EXCLUDED.mean_arima_rmse,
                    mean_xgb_rmse = EXCLUDED.mean_xgb_rmse,
                    pct_rmse_improvement = EXCLUDED.pct_rmse_improvement,
                    xgb_wins = EXCLUDED.xgb_wins,
                    wilcoxon_statistic = EXCLUDED.wilcoxon_statistic,
                    p_value = EXCLUDED.p_value,
                    significant_at_0_05 = EXCLUDED.significant_at_0_05,
                    updated_at = now()
                """,
                (
                    summary["n_symbols"],
                    summary["mean_arima_rmse"],
                    summary["mean_xgb_rmse"],
                    summary["pct_rmse_improvement"],
                    summary["xgb_wins"],
                    summary["wilcoxon_statistic"],
                    summary["p_value"],
                    summary["significant_at_0.05"],
                ),
            )

            for symbol, m in per_symbol.items():
                cur.execute(
                    """
                    INSERT INTO model_metrics
                        (symbol, arima_order, arima_rmse, xgb_rmse,
                         adf_statistic, adf_p_value, adf_stationary,
                         ljung_box_p_value, ljung_box_white_noise, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (symbol) DO UPDATE SET
                        arima_order = EXCLUDED.arima_order,
                        arima_rmse = EXCLUDED.arima_rmse,
                        xgb_rmse = EXCLUDED.xgb_rmse,
                        adf_statistic = EXCLUDED.adf_statistic,
                        adf_p_value = EXCLUDED.adf_p_value,
                        adf_stationary = EXCLUDED.adf_stationary,
                        ljung_box_p_value = EXCLUDED.ljung_box_p_value,
                        ljung_box_white_noise = EXCLUDED.ljung_box_white_noise,
                        updated_at = now()
                    """,
                    (
                        symbol,
                        str(m["arima_order"]),
                        m["arima_rmse"],
                        m["xgb_rmse"],
                        m["adf"]["statistic"],
                        m["adf"]["p_value"],
                        m["adf"]["is_stationary"],
                        m["ljung_box"]["p_value"],
                        m["ljung_box"]["is_white_noise"],
                    ),
                )

            for symbol, s in series.items():
                # Delete-then-insert per symbol keeps re-running the loader
                # (e.g. after a fresh pipeline run) idempotent, since COPY
                # itself can't express ON CONFLICT.
                cur.execute("DELETE FROM forecast_points WHERE symbol = %s", (symbol,))
                rows = list(zip(s["dates"], s["actual"], s["arima_pred"], s["xgb_pred"]))
                with cur.copy(
                    "COPY forecast_points (symbol, date, actual, arima_pred, xgb_pred) FROM STDIN"
                ) as copy:
                    for date, actual, arima_pred, xgb_pred in rows:
                        copy.write_row((symbol, date, actual, arima_pred, xgb_pred))

    print(f"Loaded {len(per_symbol)} symbols' metrics and forecast series into Postgres.")


if __name__ == "__main__":
    load()
