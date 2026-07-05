"""
Walk-forward evaluation: refit both models every REFIT_EVERY trading days
on an expanding window and forecast the next REFIT_EVERY days, over the
final TEST_DAYS of each symbol's history. This is the standard
"rolling-origin" backtest used for time-series model comparison — it
never lets either model see future data it wouldn't have had in
production.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from models import (
    build_features,
    fit_arima,
    fit_xgb,
    forecast_arima,
    forecast_xgb,
    select_arima_order,
)

TEST_DAYS = 252  # ~1 trading year held out
REFIT_EVERY = 20  # ~1 trading month between refits


def evaluate_symbol(df: pd.DataFrame) -> dict | None:
    """Returns per-symbol RMSE for both models plus the fitted ARIMA
    residuals (for the Ljung-Box diagnostic) and the full actual/predicted
    series (for charting), or None if there isn't enough history.
    """
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < TEST_DAYS + 300:
        return None

    close = df["close"]
    feats = build_features(df)

    split_idx = len(df) - TEST_DAYS
    arima_order = select_arima_order(close.iloc[:split_idx])

    arima_preds, xgb_preds, actuals, dates = [], [], [], []
    last_arima_fit = None

    step = 0
    while split_idx + step < len(df):
        window_end = split_idx + step
        horizon = min(REFIT_EVERY, len(df) - window_end)

        train_close = close.iloc[:window_end]
        train_feats = feats.iloc[:window_end].dropna()

        arima_fit = fit_arima(train_close, arima_order)
        last_arima_fit = arima_fit
        xgb_model = fit_xgb(train_feats)

        a_forecast = forecast_arima(arima_fit, horizon)

        for h in range(horizon):
            idx = window_end + h
            row = feats.iloc[[idx]]
            if row.isna().any(axis=None):
                continue
            xgb_preds.append(forecast_xgb(xgb_model, row))
            arima_preds.append(a_forecast[h])
            actuals.append(close.iloc[idx])
            dates.append(df["date"].iloc[idx])

        step += horizon

    if len(actuals) < 30:
        return None

    actuals = np.array(actuals)
    arima_preds = np.array(arima_preds)
    xgb_preds = np.array(xgb_preds)

    arima_rmse = float(np.sqrt(np.mean((actuals - arima_preds) ** 2)))
    xgb_rmse = float(np.sqrt(np.mean((actuals - xgb_preds) ** 2)))

    return {
        "arima_order": arima_order,
        "arima_rmse": arima_rmse,
        "xgb_rmse": xgb_rmse,
        "arima_residuals": last_arima_fit.resid.tolist() if last_arima_fit is not None else [],
        "dates": [str(d)[:10] for d in dates],
        "actual": actuals.tolist(),
        "arima_pred": arima_preds.tolist(),
        "xgb_pred": xgb_preds.tolist(),
        "close_series": close.tolist(),
        "date_series": [str(d)[:10] for d in df["date"]],
    }
