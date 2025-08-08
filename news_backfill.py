import os
import psycopg
from datetime import datetime, timedelta, timezone

# per SDK README, import path is this:
from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest

# --- ENV / DB URL normalize ---
raw_url = os.environ["DB_URL"].strip()
DB_URL = raw_url.replace("postgresql+psycopg://", "postgresql://")
if "sslmode=" not in DB_URL:
    DB_URL += ("&" if "?" in DB_URL else "?") + "sslmode=require"

ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_API_SECRET = os.environ["ALPACA_API_SECRET"]
SYMBOLS = [s.strip().upper() for s in os.environ["SYMBOLS"].split(",") if s.strip()]

# --- ensure table exists ---
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS news (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    headline TEXT,
    summary TEXT,
    author TEXT,
    source TEXT,
    url TEXT,
    published_at TIMESTAMPTZ
);
"""
with psycopg.connect(DB_URL) as conn:
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()

news_client = NewsClient(api_key=ALPACA_API_KEY, secret_key=ALPACA_API_SECRET)

start_date = (datetime.now(timezone.utc) - timedelta(days=730)).date()
end_date = datetime.now(timezone.utc).date()

for symbol in SYMBOLS:
    print(f"[news_backfill] {symbol}: {start_date} → {end_date}")
    page_token = None

    while True:
        req = NewsRequest(
            symbols=symbol,           # <- string, not list
            start=start_date,
            end=end_date,
            limit=50,
            page_token=page_token
        )
        page = news_client.get_news(req)

        # Use the DataFrame the SDK provides
        df = getattr(page, "df", None)
        if df is None or df.empty:
            break

        # Normalize expected columns
        # DF columns typically include: id, headline, summary, author(s), source, url, created_at, symbols, etc.
        rows = []
        for _, r in df.iterrows():
            rows.append((
                str(r.get("id")),
                symbol,
                r.get("headline"),
                r.get("summary"),
                # authors may be a list or string depending on version
                ", ".join(r["authors"]) if isinstance(r.get("authors"), (list, tuple)) else r.get("author") or r.get("authors"),
                r.get("source"),
                r.get("url"),
                r.get("created_at")
            ))

        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO news (id, symbol, headline, summary, author, source, url, published_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO NOTHING;
                    """,
                    rows
                )
            conn.commit()

        # paginate if available
        page_token = getattr(page, "next_page_token", None)
        if not page_token:
            break

print("[news_backfill] Done.")
