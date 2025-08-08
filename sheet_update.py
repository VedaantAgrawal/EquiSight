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
