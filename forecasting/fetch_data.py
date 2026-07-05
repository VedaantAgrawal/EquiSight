"""
Pulls 5+ years of daily OHLCV history for the symbol universe via yfinance
(free, no API key required). Caches each symbol to a local parquet file so
the modeling step doesn't need to re-download on every run.
"""

import os
import time

import pandas as pd
import yfinance as yf

from symbols import SYMBOLS

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data_cache")
PERIOD = "5y"


def fetch_symbol(symbol: str) -> pd.DataFrame:
    df = yf.download(symbol, period=PERIOD, auto_adjust=True, progress=False)
    if df.empty:
        return df
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df = df.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
    df.columns = ["date", "open", "high", "low", "close", "volume"]
    return df


def fetch_all(symbols=SYMBOLS, force=False) -> dict[str, pd.DataFrame]:
    os.makedirs(CACHE_DIR, exist_ok=True)
    out = {}
    for i, sym in enumerate(symbols):
        cache_path = os.path.join(CACHE_DIR, f"{sym}.csv")
        if not force and os.path.exists(cache_path):
            out[sym] = pd.read_csv(cache_path, parse_dates=["date"])
            continue
        try:
            df = fetch_symbol(sym)
        except Exception as e:
            print(f"[fetch] {sym} failed: {e}")
            continue
        if df.empty or len(df) < 500:  # need enough history for 5y daily
            print(f"[fetch] {sym} skipped: insufficient data ({len(df)} rows)")
            continue
        df.to_csv(cache_path, index=False)
        out[sym] = df
        print(f"[fetch] {sym}: {len(df)} rows ({i + 1}/{len(symbols)})")
        time.sleep(0.3)  # light pacing to avoid rate limits
    return out


if __name__ == "__main__":
    data = fetch_all()
    print(f"\nFetched {len(data)}/{len(SYMBOLS)} symbols successfully.")
