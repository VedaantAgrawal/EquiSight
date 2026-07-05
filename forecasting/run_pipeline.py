"""
End-to-end pipeline: fetch data -> evaluate ARIMA vs XGBoost per symbol ->
run statistical tests -> write results to forecasting/results/.

Run directly (python3 run_pipeline.py) for a local dry-run that produces
committed result files. The same functions are reused by db_write.py to
push results into Postgres for the FastAPI backend to serve.
"""

import json
import os
import time

from evaluate import evaluate_symbol
from fetch_data import fetch_all
from stats_tests import adf_test, ljung_box_test, paired_model_comparison
from symbols import SYMBOLS

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def run():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"Fetching data for {len(SYMBOLS)} symbols...")
    data = fetch_all(SYMBOLS)

    per_symbol_results = {}
    arima_rmses, xgb_rmses = [], []

    start = time.time()
    for i, (sym, df) in enumerate(data.items()):
        t0 = time.time()
        result = evaluate_symbol(df)
        if result is None:
            print(f"[{i+1}/{len(data)}] {sym}: skipped (insufficient data)")
            continue

        adf_result = adf_test(result["close_series"])
        lb_result = ljung_box_test(result["arima_residuals"])

        per_symbol_results[sym] = {
            "arima_order": result["arima_order"],
            "arima_rmse": result["arima_rmse"],
            "xgb_rmse": result["xgb_rmse"],
            "adf": adf_result,
            "ljung_box": lb_result,
            "dates": result["dates"],
            "actual": result["actual"],
            "arima_pred": result["arima_pred"],
            "xgb_pred": result["xgb_pred"],
        }
        arima_rmses.append(result["arima_rmse"])
        xgb_rmses.append(result["xgb_rmse"])

        print(
            f"[{i+1}/{len(data)}] {sym}: ARIMA RMSE={result['arima_rmse']:.3f}  "
            f"XGB RMSE={result['xgb_rmse']:.3f}  ({time.time()-t0:.1f}s)"
        )

    comparison = paired_model_comparison(arima_rmses, xgb_rmses)
    print("\n=== Aggregate comparison ===")
    print(json.dumps(comparison, indent=2))

    with open(os.path.join(RESULTS_DIR, "comparison_summary.json"), "w") as f:
        json.dump(comparison, f, indent=2)

    # Per-symbol file kept separate from the (larger) per-day series so the
    # summary is easy to scan; full series is what the API/frontend chart.
    per_symbol_summary = {
        sym: {
            "arima_order": r["arima_order"],
            "arima_rmse": r["arima_rmse"],
            "xgb_rmse": r["xgb_rmse"],
            "adf": r["adf"],
            "ljung_box": r["ljung_box"],
        }
        for sym, r in per_symbol_results.items()
    }
    with open(os.path.join(RESULTS_DIR, "per_symbol_summary.json"), "w") as f:
        json.dump(per_symbol_summary, f, indent=2)

    with open(os.path.join(RESULTS_DIR, "forecast_series.json"), "w") as f:
        json.dump(
            {
                sym: {
                    "dates": r["dates"],
                    "actual": r["actual"],
                    "arima_pred": r["arima_pred"],
                    "xgb_pred": r["xgb_pred"],
                }
                for sym, r in per_symbol_results.items()
            },
            f,
        )

    print(f"\nTotal runtime: {(time.time()-start)/60:.1f} min")
    print(f"Results written to {RESULTS_DIR}")


if __name__ == "__main__":
    run()
