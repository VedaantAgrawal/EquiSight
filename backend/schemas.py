from typing import List, Optional

from pydantic import BaseModel


class SymbolMetrics(BaseModel):
    symbol: str
    arima_order: str
    arima_rmse: float
    xgb_rmse: float
    adf_statistic: Optional[float]
    adf_p_value: Optional[float]
    adf_stationary: Optional[bool]
    ljung_box_p_value: Optional[float]
    ljung_box_white_noise: Optional[bool]


class ComparisonSummary(BaseModel):
    n_symbols: int
    mean_arima_rmse: float
    mean_xgb_rmse: float
    pct_rmse_improvement: float
    xgb_wins: int
    wilcoxon_statistic: float
    p_value: float
    significant_at_0_05: bool
    updated_at: str


class ForecastSeries(BaseModel):
    symbol: str
    dates: List[str]
    actual: List[float]
    arima_pred: List[float]
    xgb_pred: List[float]
