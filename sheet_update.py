import os
import json
from datetime import timezone
import psycopg
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread import WorksheetNotFound

# ========= ENV / CONNECTIONS =========
# Neon
raw_url = os.environ["DB_URL"].strip()  # may be postgresql+psycopg:// or postgresql://
DB_URL = raw_url.replace("postgresql+psycopg://", "postgresql://")
if "sslmode=" not in DB_URL:
    DB_URL += ("&" if "?" in DB_URL else "?") + "sslmode=require"

# Google Sheets
SHEET_ID = os.environ["SHEET_ID"]
SA_JSON  = os.environ["GCP_SERVICE_ACCOUNT"]   # full JSON string for service account

# Sheet tab names (you said: Sheet1 for OHLCV, "Sheet 2" for news)
OHLCV_TAB = os.getenv("OHLCV_SHEET_TAB", "Sheet1")
NEWS_TAB  = os.getenv("NEWS_SHEET_TAB",  "Sheet 2")

# Bars table details (so we don’t need to hardcode your schema)
BARS_TABLE   = os.getenv("BARS_TABLE", "bars")                 # change if your table is different
BARS_TS_COL  = os.getenv("BARS_TS_COL", "timestamp_utc")       # change if your ts column is different

def gs_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(SA_JSON), scopes)
    return gspread.authorize(creds)

# ========= FETCH FROM NEON =========
def fetch_todays_ohlcv():
    """
    Reads today's rows from your bars table.
    Expected columns: symbol, <ts>, open, high, low, close, volume
    """
    sql = f"""
        SELECT
          symbol,
          {BARS_TS_COL} AS timestamp_utc,
          open, high, low, close, volume
        FROM {BARS_TABLE}
        WHERE {BARS_TS_COL}::date = CURRENT_DATE
        ORDER BY symbol, {BARS_TS_COL};
    """
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [d.name for d in cur.description]
    return cols, rows

def fetch_todays_news():
    """
    Reads today's rows from persistent `news` table.
    Columns: symbol, published_at, source, headline, summary, author, url, id
    """
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

# ========= WRITE TO SHEETS =========
def ensure_ws(sh, title: str):
    try:
        return sh.worksheet(title)
    except WorksheetNotFound:
        # Make a new tab if missing
        return sh.add_worksheet(title=title, rows=2000, cols=20)

def write_sheet(tab_name: str, cols, rows, ts_index: int | None):
    """
    Clears tab and writes header+rows. If ts_index is provided, convert it to ISO UTC.
    """
    gc = gs_client()
    sh = gc.open_by_key(SHEET_ID)
    ws = ensure_ws(sh, tab_name)

    # Clear existing content
    ws.clear()

    values = [cols]
    for r in rows:
        r = list(r)
        if ts_index is not None and 0 <= ts_index < len(r):
            ts = r[ts_index]
            if ts is not None and hasattr(ts, "astimezone"):
                r[ts_index] = ts.astimezone(timezone.utc).isoformat()
        values.append(r)

    # Use new signature to avoid DeprecationWarning: values first, then range_name
    ws.update(values=values, range_name="A1", value_input_option="RAW")

def main():
    # ---- OHLCV → Sheet1 ----
    o_cols, o_rows = fetch_todays_ohlcv()
    # Find the timestamp column index in returned columns
    try:
        o_ts_idx = o_cols.index("timestamp_utc")
    except ValueError:
        o_ts_idx = None
    write_sheet(OHLCV_TAB, o_cols, o_rows, ts_index=o_ts_idx)
    print(f"[sheet_update] OHLCV: wrote {len(o_rows)} rows to '{OHLCV_TAB}'")

    # ---- NEWS → "Sheet 2" ----
    n_cols, n_rows = fetch_todays_news()
    # published_at is the second column per SELECT (index 1)
    try:
        n_ts_idx = n_cols.index("published_at")
    except ValueError:
        n_ts_idx = None
    write_sheet(NEWS_TAB, n_cols, n_rows, ts_index=n_ts_idx)
    print(f"[sheet_update] NEWS: wrote {len(n_rows)} rows to '{NEWS_TAB}'")

if __name__ == "__main__":
    main()
