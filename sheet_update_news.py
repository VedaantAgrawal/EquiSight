import os, json, time, requests
from datetime import datetime, timezone, timedelta, date

import psycopg
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread import WorksheetNotFound

# ----------------- ENV -----------------
# Neon DB
raw_db_url = os.environ["DB_URL"].strip()  # postgresql+psycopg:// or postgresql://
DB_URL = raw_db_url.replace("postgresql+psycopg://", "postgresql://")
if "sslmode=" not in DB_URL:
    DB_URL += ("&" if "?" in DB_URL else "?") + "sslmode=require"

# Alpaca
ALPACA_API_KEY    = os.environ["ALPACA_API_KEY"]
ALPACA_API_SECRET = os.environ["ALPACA_API_SECRET"]
SYMBOLS = [s.strip().upper() for s in os.environ["SYMBOLS"].split(",") if s.strip()]
BASE_URL = "https://data.alpaca.markets/v1beta1/news"
HEADERS  = {"Apca-Api-Key-Id": ALPACA_API_KEY, "Apca-Api-Secret-Key": ALPACA_API_SECRET}

# Google Sheets (dedicated news sheet)
SHEET_ID = os.environ["SHEET_ID_NEWS"]  # <- NEW: separate sheet for news
SA_JSON  = os.environ["GCP_SERVICE_ACCOUNT"]  # reuse existing service account JSON
NEWS_TAB = os.getenv("NEWS_SHEET_TAB", "Sheet1")  # first tab in the news sheet

# Behavior knobs
PAGE_LIMIT  = int(os.getenv("NEWS_PAGE_LIMIT", "50"))
PAUSE_SEC   = float(os.getenv("NEWS_PAUSE_SEC", "0.15"))
OVERLAP_HRS = int(os.getenv("NEWS_OVERLAP_HOURS", "2"))  # catch late stories
CLEAR_ONLY  = os.getenv("CLEAR_ONLY", "0") == "1"         # nightly wipe

# ----------------- SCHEMA -----------------
DDL_NEWS = """
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
DDL_NEWS_IDX = "CREATE INDEX IF NOT EXISTS news_symbol_time_idx ON news (symbol, published_at DESC);"

def ensure_news_table():
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL_NEWS)
            cur.execute(DDL_NEWS_IDX)
        conn.commit()

# ----------------- SHEETS -----------------
def gs_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(SA_JSON), scopes)
    return gspread.authorize(creds)

def get_news_ws():
    gc = gs_client()
    sh = gc.open_by_key(SHEET_ID)
    try:
        return sh.worksheet(NEWS_TAB)
    except WorksheetNotFound:
        return sh.add_worksheet(title=NEWS_TAB, rows=2000, cols=20)

def clear_sheet():
    ws = get_news_ws()
    ws.clear()
    ws.update(values=[["symbol","published_at","source","headline","summary","author","url","id"]],
              range_name="A1",
              value_input_option="RAW")
    print(f"[sheet_update_news] Cleared '{NEWS_TAB}'")

# ----------------- DB UPSERT -----------------
def upsert_news(rows):
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

# ----------------- ALPACA FETCH -----------------
def fetch_symbol_news(symbol: str, start_d: date, end_d: date) -> int:
    total = 0
    page_token = None
    while True:
        params = {
            "symbols": symbol,
            "start": start_d.isoformat(),
            "end":   end_d.isoformat(),
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

        batch = []
        for a in articles:
            aid = str(a.get("id") or a.get("_id") or a.get("guid") or "")
            if not aid:
                continue
            authors = a.get("authors")
            if isinstance(authors, list):
                authors = ", ".join(authors)
            published = a.get("created_at") or a.get("published_at")
            batch.append((
                aid,
                symbol,
                a.get("headline"),
                a.get("summary"),
                authors or a.get("author"),
                a.get("source"),
                a.get("url"),
                published,
            ))

        total += upsert_news(batch)
        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(PAUSE_SEC)
    return total

# ----------------- READ TODAY FROM DB & WRITE SHEET -----------------
def fetch_todays_news_from_db():
    sql = """
        SELECT symbol, published_at, source, headline, summary, author, url, id
        FROM news
        WHERE published_at::date = CURRENT_DATE
        ORDER BY symbol, published_at DESC;
    """
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [d.name for d in cur.description]
    return cols, rows

def write_sheet(cols, rows):
    ws = get_news_ws()
    # Clear & rewrite
    ws.clear()
    values = [cols]
    for r in rows:
        rr = list(r)
        # published_at at index 1 in SELECT above
        ts = rr[1]
        if ts is not None and hasattr(ts, "astimezone"):
            rr[1] = ts.astimezone(timezone.utc).isoformat()
        values.append(rr)
    ws.update(values=values, range_name="A1", value_input_option="RAW")
    print(f"[sheet_update_news] Wrote {len(rows)} rows to '{NEWS_TAB}'")

# ----------------- MAIN -----------------
def main():
    if CLEAR_ONLY:
        clear_sheet()
        return

    ensure_news_table()

    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(hours=OVERLAP_HRS)).date()
    end_date   = now.date()

    total = 0
    for sym in SYMBOLS:
        n = fetch_symbol_news(sym, start_date, end_date)
        print(f"[sheet_update_news] {sym}: +{n} rows ({start_date} → {end_date})")
        total += n
        time.sleep(PAUSE_SEC)
    print(f"[sheet_update_news] Upserted ~{total} rows to Neon.")

    cols, rows = fetch_todays_news_from_db()
    write_sheet(cols, rows)

if __name__ == "__main__":
    main()
