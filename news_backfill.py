import os
import psycopg
from alpaca.data.historical import NewsClient
from alpaca.data.requests import NewsRequest
from datetime import datetime, timedelta, timezone

# --- ENV ---
raw_url = os.environ["DB_URL"].strip()  # may be postgresql+psycopg://... or postgresql://...
# normalize SQLAlchemy URL to psycopg DSN
DB_URL = raw_url.replace("postgresql+psycopg://", "postgresql://")
if "sslmode=" not in DB_URL:
    DB_URL += ("&" if "?" in DB_URL else "?") + "sslmode=require"

ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_API_SECRET = os.environ["ALPACA_API_SECRET"]
SYMBOLS = [s.strip().upper() for s in os.environ["SYMBOLS"].split(",") if s.strip()]

# --- Ensure table exists ---
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

# --- Alpaca client ---
news_client = NewsClient(api_key=ALPACA_API_KEY, secret_key=ALPACA_API_SECRET)

# --- Backfill window (2 years) ---
start_date = (datetime.now(timezone.utc) - timedelta(days=730)).date()
end_date = datetime.now(timezone.utc).date()

for symbol in SYMBOLS:
    print(f"[news_backfill] {symbol}: {start_date} → {end_date}")
    page_token = None
    while True:
        req = NewsRequest(
            symbols=symbol,
            start=start_date,
            end=end_date,
            limit=50,
            page_token=page_token
        )
        resp = news_client.get_news(req)

        if not resp.news:
            break

        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                for item in resp.news:
                    cur.execute(
                        """
                        INSERT INTO news (id, symbol, headline, summary, author, source, url, published_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (id) DO NOTHING;
                        """,
                        (
                            item.id,
                            symbol,
                            getattr(item, "headline", None),
                            getattr(item, "summary", None),
                            ", ".join(getattr(item, "authors", []) or []) or getattr(item, "author", None),
                            getattr(item, "source", None),
                            getattr(item, "url", None),
                            getattr(item, "created_at", None),
                        ),
                    )
            conn.commit()

        page_token = getattr(resp, "next_page_token", None)
        if not page_token:
            break

print("[news_backfill] Done.")
