import os
import time
import psycopg
from datetime import datetime, timedelta, timezone

from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest

# -------- ENV --------
raw_url = os.environ["DB_URL"].strip()                    # can be postgresql+psycopg:// or postgresql://
DB_URL = raw_url.replace("postgresql+psycopg://", "postgresql://")
if "sslmode=" not in DB_URL:
    DB_URL += ("&" if "?" in DB_URL else "?") + "sslmode=require"

ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_API_SECRET = os.environ["ALPACA_API_SECRET"]
SYMBOLS = [s.strip().upper() for s in os.environ["SYMBOLS"].split(",") if s.strip()]
WINDOW_HOURS = int(os.getenv("NEWS_WINDOW_HOURS", "48"))  # safe overlap window
PAGE_LIMIT = int(os.getenv("NEWS_PAGE_LIMIT", "50"))      # Alpaca page size
PAUSE_SEC = float(os.getenv("NEWS_PAUSE_SEC", "0.2"))     # polite pacing
# ---------------------

DDL_CREATE = """
CREATE TABLE IF NOT EXISTS news (
    id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    headline TEXT,
    summary TEXT,
    author TEXT,
    source TEXT,
    url TEXT,
    published_at TIMESTAMPTZ,
    PRIMARY KEY (id, symbol)
);
"""
DDL_INDEX = "CREATE INDEX IF NOT EXISTS news_symbol_time_idx ON news (symbol, published_at DESC);"

def ensure_schema():
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL_CREATE)
            cur.execute(DDL_INDEX)
        conn.commit()

def upsert_rows(rows):
    if not rows:
        return 0
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO news (id, symbol, headline, summary, author, source, url, published_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id, symbol) DO NOTHING;
                """,
                rows
            )
        conn.commit()
    return len(rows)

def fetch_symbol(symbol: str, start_dt, end_dt) -> int:
    client = NewsClient(api_key=ALPACA_API_KEY, secret_key=ALPACA_API_SECRET)
    total = 0
    page_token = None
    while True:
        req = NewsRequest(
            symbols=symbol,             # string, not list
            start=start_dt,
            end=end_dt,
            limit=PAGE_LIMIT,
            page_token=page_token,
            sort="asc"
        )
        page = client.get_news(req)
        df = getattr(page, "df", None)
        if df is None or df.empty:
            break

        rows = []
        for _, r in df.iterrows():
            authors = r.get("authors")
            if isinstance(authors, (list, tuple)):
                authors = ", ".join(authors)
            if not authors:
                authors = r.get("author")

            rows.append((
                str(r.get("id")),
                symbol,
                r.get("headline"),
                r.get("summary"),
                authors,
                r.get("source"),
                r.get("url"),
                r.get("created_at")
            ))
        total += upsert_rows(rows)

        page_token = getattr(page, "next_page_token", None)
        if not page_token:
            break
        time.sleep(PAUSE_SEC)
    return total

def run():
    ensure_schema()
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(hours=WINDOW_HOURS)
    grand = 0
    for sym in SYMBOLS:
        n = fetch_symbol(sym, start_dt.date(), end_dt.date())
        print(f"[news_update] {sym}: +{n} rows ({start_dt.date()} → {end_dt.date()})")
        grand += n
        time.sleep(PAUSE_SEC)
    print(f"[news_update] Done. Inserted ~{grand} rows this run.")

if __name__ == "__main__":
    run()
