"""
The three statistical tests referenced on the resume:

1. ADF (Augmented Dickey-Fuller) — tests whether each symbol's raw price
   series is stationary. Expected result: non-stationary in levels,
   which is exactly why ARIMA is fit on first differences (d=1).
2. Ljung-Box — tests whether the fitted ARIMA model's residuals are
   white noise (no leftover autocorrelation). A good fit should not
   reject the null hypothesis at usual significance levels.
3. Wilcoxon signed-rank test — a paired, non-parametric test comparing
   XGBoost's per-symbol RMSE against ARIMA's per-symbol RMSE across the
   whole universe, producing the actual p-value for "XGBoost beats
   ARIMA at p < 0.05."
"""

import numpy as np
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import adfuller


def adf_test(series) -> dict:
    series = np.asarray(series, dtype=float)
    series = series[~np.isnan(series)]
    stat, pvalue, *_ = adfuller(series, autolag="AIC")
    return {
        "statistic": float(stat),
        "p_value": float(pvalue),
        "is_stationary": bool(pvalue < 0.05),
    }


def ljung_box_test(residuals, lags: int = 10) -> dict:
    residuals = np.asarray(residuals, dtype=float)
    residuals = residuals[~np.isnan(residuals)]
    if len(residuals) < lags + 5:
        return {"p_value": None, "is_white_noise": None}
    result = acorr_ljungbox(residuals, lags=[lags], return_df=True)
    pvalue = float(result["lb_pvalue"].iloc[0])
    return {"p_value": pvalue, "is_white_noise": bool(pvalue > 0.05)}


def paired_model_comparison(arima_rmses: list[float], xgb_rmses: list[float]) -> dict:
    arima_rmses = np.asarray(arima_rmses)
    xgb_rmses = np.asarray(xgb_rmses)
    diffs = arima_rmses - xgb_rmses  # positive => xgb is better (lower RMSE)

    stat, pvalue = stats.wilcoxon(arima_rmses, xgb_rmses)

    mean_arima = float(np.mean(arima_rmses))
    mean_xgb = float(np.mean(xgb_rmses))
    pct_improvement = float((mean_arima - mean_xgb) / mean_arima * 100)

    return {
        "n_symbols": int(len(arima_rmses)),
        "mean_arima_rmse": mean_arima,
        "mean_xgb_rmse": mean_xgb,
        "pct_rmse_improvement": pct_improvement,
        "xgb_wins": int(np.sum(diffs > 0)),
        "wilcoxon_statistic": float(stat),
        "p_value": float(pvalue),
        "significant_at_0.05": bool(pvalue < 0.05),
    }
