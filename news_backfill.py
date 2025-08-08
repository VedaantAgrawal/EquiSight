import os
import psycopg
from alpaca.data.historical import NewsClient
from alpaca.data.requests import NewsRequest
from datetime import datetime, timedelta, timezone

# ===== ENV VARS =====
DB_URL = os.environ["DB_URL"]
ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_API_SECRET = os.environ["ALPACA_API_SECRET"]
SYMBOLS = os.environ["SYMBOLS"].split(",")  # comma-separated in GitHub Secrets
# ====================

# Alpaca News client
news_client = NewsClient(api_key=ALPACA_API_KEY, secret_key=ALPACA_API_SECRET)

# Create table if not exists
create_table_sql = """
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
        cur.execute(create_table_sql)
    conn.commit()

# Backfill for last 2 years
start_date = (datetime.now(timezone.utc) - timedelta(days=730)).date()
end_date = datetime.now(timezone.utc).date()

for symbol in SYMBOLS:
    print(f"[news_backfill] Fetching news for {symbol} from {start_date} to {end_date}")
    page_token = None
    while True:
        req = NewsRequest(
            symbols=[symbol],
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
                    cur.execute("""
                        INSERT INTO news (id, symbol, headline, summary, author, source, url, published_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (id) DO NOTHING;
                    """, (
                        item.id,
                        symbol,
                        item.headline,
                        item.summary,
                        ", ".join(item.authors) if item.authors else None,
                        item.source,
                        item.url,
                        item.created_at
                    ))
            conn.commit()

        page_token = resp.next_page_token
        if not page_token:
            break

print("[news_backfill] Done.")
