import os, time, psycopg, requests
from datetime import datetime, timedelta, timezone

# ---------- ENV / CONFIG ----------
raw_url = os.environ["DB_URL"].strip()  # may be postgresql+psycopg:// or postgresql://
DB_URL = raw_url.replace("postgresql+psycopg://", "postgresql://")
if "sslmode=" not in DB_URL:
    DB_URL += ("&" if "?" in DB_URL else "?") + "sslmode=require"

ALPACA_API_KEY    = os.environ["ALPACA_API_KEY"]
ALPACA_API_SECRET = os.environ["ALPACA_API_SECRET"]
SYMBOLS = [s.strip().upper() for s in os.environ["SYMBOLS"].split(",") if s.strip()]

# Overlap window so late/paginated stories still get captured each run
WINDOW_HOURS = int(os.getenv("NEWS_WINDOW_HOURS", "48"))
PAGE_LIMIT   = int(os.getenv("NEWS_PAGE_LIMIT", "50"))
PAUSE_SEC    = float(os.getenv("NEWS_PAUSE_SEC", "0.2"))

BASE_URL = "https://data.alpaca.markets/v1beta1/news"
HEADERS  = {"Apca-Api-Key-Id": ALPACA_API_KEY, "Apca-Api-Secret-Key": ALPACA_API_SECRET}

# ---------- SCHEMA (day-only table) ----------
DDL_TODAY = """
CREATE TABLE IF NOT EXISTS today_news (
    id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    headline TEXT,
    summary TEXT,
    author TEXT,
    source TEXT,
    url TEXT,
    published_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id, symbol)
);
"""
DDL_IDX = "CREATE INDEX IF NOT EXISTS today_news_symbol_time_idx ON today_news (symbol, published_at DESC);"

def ensure_today_table():
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL_TODAY)
            cur.execute(DDL_IDX)
        conn.commit()

def wipe_if_old_day():
    """Keep only CURRENT_DATE rows so table is 'today only'."""
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM today_news WHERE published_at::date < CURRENT_DATE;")
        conn.commit()

def upsert_today(rows):
    if not rows:
        return 0
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO today_news (id, symbol, headline, summary, author, source, url, published_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id, symbol) DO NOTHING;
                """,
                rows
            )
        conn.commit()
    return len(rows)

def fetch_symbol(symbol: str, start_date, end_date) -> int:
    """Fetch news for one symbol between inclusive dates, paging via page_token."""
    total = 0
    page_token = None
    while True:
        params = {
            "symbols": symbol,
            "start": start_date.isoformat(),  # YYYY-MM-DD
            "end":   end_date.isoformat(),    # YYYY-MM-DD
            "limit": PAGE_LIMIT,
            "sort":  "asc",
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
                a.get("created_at") or a.get("published_at"),
            ))

        total += upsert_today(rows)
        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(PAUSE_SEC)
    return total

def run():
    ensure_today_table()
    wipe_if_old_day()  # ensure table is "today only" before inserting

    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(hours=WINDOW_HOURS)
    # We pass dates to the API; table will keep only CURRENT_DATE rows after wipe.
    start_date = start_dt.date()
    end_date   = now.date()

    grand = 0
    for sym in SYMBOLS:
        n = fetch_symbol(sym, start_date, end_date)
        print(f"[today_news] {sym}: +{n} rows ({start_date} → {end_date})")
        grand += n
        time.sleep(PAUSE_SEC)
    print(f"[today_news] Done. Inserted ~{grand} rows this run.")

if __name__ == "__main__":
    run()
