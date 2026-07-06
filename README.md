# EquiSight

Stock analysis and forecasting tool: a head-to-head comparison of ARIMA
against gradient-boosted (XGBoost) forecasting across 59 liquid equities,
served through a FastAPI + PostgreSQL backend and a React/Plotly dashboard.

**Live demo:** _(added once deployed — see [Deployment](#deployment))_
**API:** _(added once deployed)_

## Real, measured results

Computed by [`forecasting/run_pipeline.py`](forecasting/run_pipeline.py) —
5 years of daily price history per symbol (via `yfinance`), walk-forward
validated (expanding window, refit every 20 trading days, forecasting the
final ~1 trading year held out per symbol):

| Metric | Result |
|---|---|
| Symbols evaluated | 59 |
| Mean ARIMA RMSE | 17.03 |
| Mean XGBoost RMSE | 11.31 |
| **RMSE improvement (XGBoost over ARIMA)** | **33.6%** |
| XGBoost wins | 52 / 59 symbols |
| Wilcoxon signed-rank p-value | 2.85 × 10⁻⁹ |
| Statistically significant at α = 0.05? | Yes |

Full numbers: [`forecasting/results/comparison_summary.json`](forecasting/results/comparison_summary.json)
and [`forecasting/results/per_symbol_summary.json`](forecasting/results/per_symbol_summary.json).

Per-symbol diagnostics also included for every symbol:
- **ADF (Augmented Dickey-Fuller) test** on the raw price series —
  confirms non-stationarity, which is why ARIMA is fit on first
  differences (`d=1`).
- **Ljung-Box test** on each fitted ARIMA model's residuals — checks
  whether the model actually captured the autocorrelation structure
  (residuals should be white noise).

A note on honesty: these numbers are genuinely computed by running the
code in this repo, not asserted. Re-running `run_pipeline.py` against
live data will produce slightly different (but comparable) numbers, since
markets move and the training window shifts forward.

## Architecture

```
┌─────────────┐    ┌──────────────────┐    ┌─────────────┐    ┌──────────────┐
│  yfinance   │───▶│ forecasting/      │───▶│  Postgres   │◀───│  FastAPI      │
│ (5y daily,  │    │ run_pipeline.py    │    │ (model_     │    │  backend      │
│ 59 symbols) │    │ ARIMA + XGBoost,   │    │  metrics,   │    │  (async,      │
└─────────────┘    │ ADF/Ljung-Box/     │    │  forecast_  │    │  cached,      │
                    │ Wilcoxon           │    │  points)    │    │  gzip)        │
                    └──────────────────┘    └─────────────┘    └──────┬───────┘
                                                                        │
                                                                        ▼
                                                              ┌──────────────────┐
                                                              │  React + Vite +  │
                                                              │  Plotly dashboard│
                                                              └──────────────────┘
```

This repo also contains a **separate, already-running system**: a live
15-minute intraday OHLCV + news ingestion pipeline (Alpaca API → Postgres
→ Google Sheets → a Dash dashboard), automated via the GitHub Actions
workflows in `.github/workflows/`. That pipeline and this forecasting
system are independent — see [`app.py`](app.py), [`backfill.py`](backfill.py),
and [`update.py`](update.py) for the intraday side.

## Tech stack

- **Data**: `yfinance` (5 years daily, no API key required)
- **Modeling**: `statsmodels` (ARIMA, AIC-selected order), `XGBoost`
  (lag + rolling-window + RSI/MACD technical features), `scipy` (Wilcoxon
  signed-rank test)
- **Database**: PostgreSQL
- **Backend**: FastAPI, async SQLAlchemy (asyncpg), in-memory response
  caching, gzip compression
- **Frontend**: React + TypeScript, Vite, Plotly.js

## Running it locally

Requires Docker.

```bash
docker compose up --build
```

This starts Postgres, loads the committed real results
(`forecasting/results/*.json`) into it, starts the API at
`http://localhost:8000`, and the dashboard at `http://localhost:5173`.

To regenerate the results from scratch (re-fetches live data, re-runs
every model — takes ~5 minutes):

```bash
cd forecasting
pip install -r requirements.txt
python3 run_pipeline.py
DB_URL=postgresql://postgres:devpass@localhost:5432/equisight python3 db_load.py
```

## API reference

| Endpoint | Description |
|---|---|
| `GET /api/health` | Health check |
| `GET /api/symbols` | List of all evaluated symbols |
| `GET /api/metrics` | Aggregate comparison summary (RMSE, p-value, etc.) |
| `GET /api/metrics/symbols` | Per-symbol metrics + ADF/Ljung-Box results |
| `GET /api/forecast/{symbol}` | Actual price + ARIMA + XGBoost forecast series |

## Deployment

- **Database**: [Neon](https://neon.tech) (serverless Postgres, free tier)
- **Backend**: [Render](https://render.com) (free web service)
- **Frontend**: [Vercel](https://vercel.com) (free tier)
- **Uptime monitoring**: [UptimeRobot](https://uptimerobot.com) (free tier,
  also used to keep the free Render instance from sleeping)
