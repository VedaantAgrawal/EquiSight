import os
import json
import datetime as dt

import psycopg
import gspread
from oauth2client.service_account import ServiceAccountCredentials


# -------- Google auth (service account JSON comes from GitHub secret) --------
service_account_info = json.loads(os.environ["GCP_SERVICE_ACCOUNT"])
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, SCOPES)
gc = gspread.authorize(creds)

SHEET_ID = os.environ["SHEET_ID"]
ws = gc.open_by_key(SHEET_ID).sheet1  # use the first worksheet


# ----------------------- Build a psycopg-friendly DSN ------------------------
raw_db_url = os.environ["DB_URL"].strip()  # e.g. postgresql+psycopg://... or postgresql://...
dsn = raw_db_url.replace("postgresql+psycopg://", "postgresql://")

# Ensure Neon-required SSL flag is present
if "sslmode=" not in dsn:
    dsn = dsn + ("&" if "?" in dsn else "?") + "sslmode=require"


# ------------------------- Query today's OHLCV rows --------------------------
# Uses UTC date. If you prefer US/Eastern “trading day”, we can shift the timezone.
today_utc = dt.datetime.now(dt.timezone.utc).date()

query = """
    SELECT symbol, t, open, high, low, close, volume
    FROM ohlcv_bars
    WHERE t::date = %s
    ORDER BY symbol, t;
"""

with psycopg.connect(dsn) as conn:
    with conn.cursor() as cur:
        cur.execute(query, (today_utc,))
        rows = cur.fetchall()


# --------------------------- Write to Google Sheet ---------------------------
# Build data array (header + all rows) and push in ONE update for speed.
header = ["symbol", "timestamp_utc", "open", "high", "low", "close", "volume"]
data = [header]
for symbol, ts, o, h, l, c, v in rows:
    # standardize timestamp for Sheets
    data.append([symbol, ts.isoformat(), o, h, l, c, v])

# Clear entire sheet, then write starting at A1
ws.clear()
ws.update("A1", data, value_input_option="RAW")

print(f"[sheet_update] Wrote {len(rows)} rows to Google Sheet for {today_utc}")

# =========================
# NEWS → Google Sheets ("Sheet 2")
# =========================

NEWS_TAB_NAME = os.getenv("NEWS_SHEET_TAB", "Sheet 2")  # you said you created "Sheet 2" manually

def _gs_client():
    """Reuse your service account JSON in env GCP_SERVICE_ACCOUNT to auth gspread."""
    sa_json = os.environ.get("GCP_SERVICE_ACCOUNT")
    if not sa_json:
        raise RuntimeError("GCP_SERVICE_ACCOUNT env var is missing")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(sa_json), scopes)
    return gspread.authorize(creds)

def fetch_todays_news_rows():
    """Fetch today's (UTC) news rows from the persistent `news` table."""
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

def write_news_to_sheet2():
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        raise RuntimeError("SHEET_ID env var is missing")

    cols, rows = fetch_todays_news_rows()

    gc = _gs_client()
    sh = gc.open_by_key(sheet_id)

    try:
        ws = sh.worksheet(NEWS_TAB_NAME)
    except WorksheetNotFound:
        # You said you created "Sheet 2" manually; if not found, create it.
        ws = sh.add_worksheet(title=NEWS_TAB_NAME, rows=1000, cols=12)

    # Clear existing content
    ws.clear()

    # Prepare header + data
    values = [cols]
    for r in rows:
        r = list(r)
        # Ensure published_at is ISO in UTC (index 1 given the SELECT)
        if r[1] is not None and hasattr(r[1], "astimezone"):
            r[1] = r[1].astimezone(timezone.utc).isoformat()
        values.append(r)

    # Write starting at A1 (note: values first, then range_name to avoid deprecation warning)
    ws.update(values=values, range_name="A1", value_input_option="RAW")
    print(f"[sheet_update_news] Wrote {len(rows)} rows to '{NEWS_TAB_NAME}'")

# ---- Call the news writer at the very end of your script's main flow ----
if __name__ == "__main__":
    # your existing stock/ohlcv writing code runs first...
    # then append:
    try:
        write_news_to_sheet2()
    except Exception as e:
        print(f"[sheet_update_news] Failed to write news: {e}")

