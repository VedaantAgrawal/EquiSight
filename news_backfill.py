import os
import psycopg
from datetime import datetime, timedelta, timezone

# Alpaca SDK (news)
from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest

# -------------------- ENV + DB URL normalize --------------------
raw_url = os.environ["DB_URL"].strip()  # may be postgresql+psycopg://... or postgresql://...
DB_URL = raw_url.replace("postgresql+psycopg://", "postgresql://")
if "sslmode=" not in DB_URL:
    DB_URL += ("&" if "?" in DB_URL else "?") + "sslmode=require"

ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_API_SECRET = os.environ["ALPACA_API_SECRET"]
SYMBOLS = [s.strip().upper() for s in os.environ["SYMBOLS"].split(",") if s.strip()]

# -------------------- Ensure table + migrate PK ------------------
DDL_CREATE = """
CREATE TABLE IF NOT EXISTS news (
    id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    headline TEXT,
    summary TEXT,
    author TEXT,
    source TEXT,
    url TEXT,
    published_at TIMESTAMPTZ
);
"""

DDL_MIGRATE = """
BEGIN;

-- Drop old single-column PK if it exists (usually news_pkey)
ALTER TABLE news DROP CONSTRAINT IF EXISTS news_pkey;

-- If no PK exists, add composite (id, symbol)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'news' AND c.contype = 'p'
  ) THEN
    ALTER TABLE news ADD PRIMARY KEY (id, symbol);
  END IF;
END$$;

-- Helpful index for queries
CREATE INDEX IF NOT EXISTS news_symbol_time_idx ON news (symbol, published_at DESC);

COMMIT;
"""

with psycopg.connect(DB_URL) as conn:
    with conn.cursor() as cur:
        cur.execute(DDL_CREATE)
        cur.execute(DDL_MIGRATE)
    conn.commit()

# -------------------- Alpaca client ------------------------------
news_client = NewsClient(api_key=ALPACA_API_KEY, secret_key=ALPACA_API_SECRET)

# 2-year backfill window
start_date = (datetime.now(timezone.utc) - timedelta(days=730)).date()
end_date = datetime.now(timezone.utc).date()

# -------------------- Backfill loop ------------------------------
for symbol in SYMBOLS:
    print(f"[news_backfill] {symbol}: {start_date} → {end_date}")
    page_token = None

    while True:
        req = NewsRequest(
            symbols=symbol,  # string (comma-separated supported too)
            start=start_date,
            end=end_date,
            limit=50,
            page_token=page_token
        )
        page = news_client.get_news(req)

        df = getattr(page, "df", None)
        if df is None or df.empty:
            break

        # Prepare rows for bulk insert
        rows = []
        for _, r in df.iterrows():
            authors = r.get("authors")
            if isinstance(authors, (list, tuple)):
                authors = ", ".join(authors)
            if not authors:
                authors = r.get("author")  # fallback if SDK shape varies

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

        page_token = getattr(page, "next_page_token", None)
        if not page_token:
            break

print("[news_backfill] Done.")
