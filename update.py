import os, datetime as dt
from tenacity import retry, wait_exponential, stop_after_attempt
from sqlalchemy import create_engine, text

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

# --- Env (from GitHub Secrets) ---
DB_URL = os.environ["DB_URL"]                 # e.g., postgresql+psycopg://.../?sslmode=require
ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_API_SECRET = os.environ["ALPACA_API_SECRET"]
ALPACA_DATA_FEED = os.getenv("ALPACA_DATA_FEED", "iex")
SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", "SPY").split(",") if s.strip()]
# ----------------------------------

engine = create_engine(DB_URL, pool_pre_ping=True, future=True)
client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)

UPSERT_SQL = """
INSERT INTO ohlcv_bars (symbol, t, open, high, low, close, volume, trade_count, vwap)
VALUES (:symbol, :t, :open, :high, :low, :close, :volume, :trade_count, :vwap)
ON CONFLICT (symbol, t) DO UPDATE SET
  open=EXCLUDED.open,
  high=EXCLUDED.high,
  low=EXCLUDED.low,
  close=EXCLUDED.close,
  volume=EXCLUDED.volume,
  trade_count=EXCLUDED.trade_count,
  vwap=EXCLUDED.vwap;
"""

def utcnow():
    return dt.datetime.now(dt.timezone.utc)

def as_utc(d: dt.datetime):
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)

@retry(wait=wait_exponential(multiplier=1, min=1, max=30), stop=stop_after_attempt(6))
def fetch_and_store(symbols, start_dt, end_dt):
    req = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame(15, TimeFrameUnit.Minute),
        start=as_utc(start_dt),
        end=as_utc(end_dt),
        feed=ALPACA_DATA_FEED,
        limit=10000
    )
    bars = client.get_stock_bars(req)

    rows = []
    for sym, barlist in bars.data.items():
        for b in barlist:
            rows.append({
                "symbol": sym,
                "t": b.timestamp,  # UTC
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": int(b.volume or 0),
                "trade_count": int(getattr(b, "trade_count", 0) or 0),
                "vwap": float(getattr(b, "vwap", 0.0) or 0.0),
            })
    if not rows:
        print("[update] No rows returned.")
        return 0
    with engine.begin() as conn:
        conn.execute(text(UPSERT_SQL), rows)
    print(f"[update] Upserted {len(rows)} rows.")
    return len(rows)

def fetch_latest_window():
    end = utcnow()
    start = end - dt.timedelta(minutes=30)  # overlap ensures late bars get captured
    fetch_and_store(SYMBOLS, start, end)

if __name__ == "__main__":
    fetch_latest_window()
