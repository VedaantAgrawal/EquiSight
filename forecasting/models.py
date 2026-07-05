"""
Two forecasting approaches compared head-to-head:

1. ARIMA (statsmodels) — classical statistical time-series model.
2. Gradient-boosted regression (XGBoost) over lagged price/technical
   features — the same family of model used for the PwC forecasting
   work described in the resume.

Both predict next-day closing price.
"""

import warnings

import numpy as np
import pandas as pd
import xgboost as xgb
from statsmodels.tsa.arima.model import ARIMA

warnings.filterwarnings("ignore")


def select_arima_order(train_close: pd.Series) -> tuple[int, int, int]:
    """Small AIC grid search over a handful of (p, 1, q) combinations.
    d=1 throughout: price series are near-universally non-stationary in
    levels (confirmed per-symbol via the ADF test in stats_tests.py),
    so first-differencing is the standard choice.
    """
    best_aic = np.inf
    best_order = (1, 1, 1)
    for p in (1, 2, 3):
        for q in (0, 1, 2):
            try:
                fit = ARIMA(train_close, order=(p, 1, q)).fit()
                if fit.aic < best_aic:
                    best_aic = fit.aic
                    best_order = (p, 1, q)
            except Exception:
                continue
    return best_order


def fit_arima(train_close: pd.Series, order: tuple[int, int, int]):
    return ARIMA(train_close, order=order).fit()


def forecast_arima(fitted_model, steps: int) -> np.ndarray:
    return np.asarray(fitted_model.forecast(steps=steps))


# ---------------------------------------------------------------------
# XGBoost: lag + rolling-window + technical-indicator feature set
# ---------------------------------------------------------------------

LAGS = (1, 2, 3, 5, 10)
ROLL_WINDOWS = (5, 10, 20)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """df must have a 'close' column, chronologically ordered."""
    feats = pd.DataFrame(index=df.index)
    close = df["close"]

    for lag in LAGS:
        feats[f"lag_{lag}"] = close.shift(lag)

    for w in ROLL_WINDOWS:
        feats[f"roll_mean_{w}"] = close.shift(1).rolling(w).mean()
        feats[f"roll_std_{w}"] = close.shift(1).rolling(w).std()

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    feats["rsi_14"] = (100 - (100 / (1 + rs))).shift(1)

    # MACD (12, 26 EMA) and signal line (9 EMA of MACD)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    feats["macd"] = macd.shift(1)
    feats["macd_signal"] = macd.ewm(span=9, adjust=False).mean().shift(1)

    feats["day_of_week"] = pd.to_datetime(df["date"]).dt.dayofweek.values

    feats["target"] = close
    return feats


def fit_xgb(train_feats: pd.DataFrame):
    X = train_feats.drop(columns=["target"])
    y = train_feats["target"]
    model = xgb.XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="reg:squarederror",
        random_state=42,
    )
    model.fit(X, y)
    return model


def forecast_xgb(model, feats_row: pd.DataFrame) -> float:
    X = feats_row.drop(columns=["target"])
    return float(model.predict(X)[0])
