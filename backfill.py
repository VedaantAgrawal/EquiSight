import os, time, datetime as dt
from tenacity import retry, wait_exponential, stop_after_attempt
from sqlalchemy import create_engine, text

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

# --- Required env vars (set as GitHub Secrets or local env) ---
DB_URL = os.environ["DB_URL"]
ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_API_SECRET = os.environ["ALPACA_API_SECRET"]
ALPACA_DATA_FEED = os.getenv("ALPACA_DATA_FEED", "iex")
SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", "SPY").split(",") if s.strip()]
# --------------------------------------------------------------

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

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

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
        return 0
    with engine.begin() as conn:
        conn.execute(text(UPSERT_SQL), rows)
    return len(rows)

def backfill_two_years():
    end = utcnow()
    start = end - dt.timedelta(days=730)

    total = 0
    cur = start
    while cur < end:
        win_end = min(cur + dt.timedelta(days=31), end)
        # Your 6 symbols will be fetched in a single batch (batch size 50 is fine)
        for batch in chunks(SYMBOLS, 50):
            total += fetch_and_store(batch, cur, win_end)
        cur = win_end
        time.sleep(0.5)  # light pacing
    print(f"[Backfill] Done. Upserted {total} rows from {start.isoformat()} to {end.isoformat()}.")

if __name__ == "__main__":
    backfill_two_years()
