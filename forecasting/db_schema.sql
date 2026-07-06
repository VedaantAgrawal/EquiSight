-- Schema for the forecasting comparison results the FastAPI backend serves.
-- Kept in its own schema/tables, separate from the existing intraday
-- ohlcv_bars/news tables used by the live 15-minute ingestion pipeline.

CREATE TABLE IF NOT EXISTS model_metrics (
    symbol           TEXT PRIMARY KEY,
    arima_order      TEXT NOT NULL,
    arima_rmse       DOUBLE PRECISION NOT NULL,
    xgb_rmse         DOUBLE PRECISION NOT NULL,
    adf_statistic    DOUBLE PRECISION,
    adf_p_value      DOUBLE PRECISION,
    adf_stationary   BOOLEAN,
    ljung_box_p_value DOUBLE PRECISION,
    ljung_box_white_noise BOOLEAN,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS forecast_points (
    symbol      TEXT NOT NULL,
    date        DATE NOT NULL,
    actual      DOUBLE PRECISION NOT NULL,
    arima_pred  DOUBLE PRECISION NOT NULL,
    xgb_pred    DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_forecast_points_symbol ON forecast_points (symbol);

CREATE TABLE IF NOT EXISTS comparison_summary (
    id                      INT PRIMARY KEY DEFAULT 1,
    n_symbols               INT NOT NULL,
    mean_arima_rmse         DOUBLE PRECISION NOT NULL,
    mean_xgb_rmse           DOUBLE PRECISION NOT NULL,
    pct_rmse_improvement    DOUBLE PRECISION NOT NULL,
    xgb_wins                INT NOT NULL,
    wilcoxon_statistic      DOUBLE PRECISION NOT NULL,
    p_value                 DOUBLE PRECISION NOT NULL,
    significant_at_0_05     BOOLEAN NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT single_row CHECK (id = 1)
);
