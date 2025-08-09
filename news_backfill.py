import os, time, psycopg, requests
from datetime import datetime, timedelta, timezone

# -------- ENV / CONFIG --------
raw_url = os.environ["DB_URL"].strip()  # may be postgresql+psycopg:// or postgresql://
DB_URL = raw_url.replace("postgresql+psycopg://", "postgresql://")
if "sslmode=" not in DB_URL:
    DB_URL += ("&" if "?" in DB_URL else "?") + "sslmode=require"

ALPACA_API_KEY    = os.environ["ALPACA_API_KEY"]
ALPACA_API_SECRET = os.environ["ALPACA_API_SECRET"]
SYMBOLS = [s.strip().upper() for s in os.environ["SYMBOLS"].split(",") if s.strip()]

# Tweakables via Action vars/secrets if needed
TOTAL_DAYS  = int(os.getenv("NEWS_TOTAL_DAYS", "730"))   # ~2 years
CHUNK_DAYS  = int(os.getenv("NEWS_CHUNK_DAYS", "30"))    # window size
PAGE_LIMIT  = int(os.getenv("NEWS_PAGE_LIMIT", "50"))
PAUSE_SEC   = float(os.getenv("NEWS_PAUSE_SEC", "0.2"))

BASE_URL = "https://data.alpaca.markets/v1beta1/news"
HEADERS  = {"Apca-Api-Key-Id": ALPACA_API_KEY, "Apca-Api-Secret-Key": ALPACA_API_SECRET}

# -------- Schema (composite PK) --------
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

def fetch_window(symbol: str, start_date, end_date) -> int:
    """Fetch one date window [start_date, end_date] for a symbol with page_token pagination."""
    total = 0
    page_token = None
    while True:
        params = {
            "symbols": symbol,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "limit": PAGE_LIMIT,
            "sort": "asc",
        }
        if page_token:
            params["page_token"] = page_token

        r = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=30)
        r.raise_for_status()
        data = r.json() or {}

        articles = data.get("news") or data.get("data") or []
        if not articles:
            break

        rows = []
        for a in articles:
            aid = str(a.get("id") or a.get("_id") or a.get("guid") or "")
            if not aid:
                continue  # skip if no stable id
            authors = a.get("authors")
            if isinstance(authors, list):
                authors = ", ".join(authors)
            rows.append((
                aid,
                symbol,
                a.get("headline"),
                a.get("summary"),
                authors or a.get("author"),
                a.get("source"),
                a.get("url"),
                a.get("created_at") or a.get("published_at")
            ))

        total += upsert_rows(rows)
        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(PAUSE_SEC)
    return total

def run():
    ensure_schema()
    end_date   = datetime.now(timezone.utc).date()
    start_date = (datetime.now(timezone.utc) - timedelta(days=TOTAL_DAYS)).date()

    for symbol in SYMBOLS:
        print(f"[news_backfill] {symbol} range {start_date} → {end_date}")
        cur_end = end_date
        grand_total = 0
        while cur_end >= start_date:
            cur_start = max(start_date, cur_end - timedelta(days=CHUNK_DAYS-1))
            n = fetch_window(symbol, cur_start, cur_end)
            grand_total += n
            print(f"  window {cur_start} → {cur_end}: +{n}")
            cur_end = cur_start - timedelta(days=1)
            time.sleep(PAUSE_SEC)
        print(f"[news_backfill] {symbol} total rows: {grand_total}")
    print("[news_backfill] Done.")

if __name__ == "__main__":
    run()
