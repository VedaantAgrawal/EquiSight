import os
import json
import datetime as dt
import psycopg
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# === Load Service Account credentials from GitHub secret ===
service_account_info = json.loads(os.environ["GCP_SERVICE_ACCOUNT"])

# === Google Sheets setup ===
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, SCOPES)
client = gspread.authorize(creds)

# === Env vars for DB ===
DB_URL = os.environ["DB_URL"]  # postgresql+psycopg://... from Neon
SHEET_ID = os.environ["SHEET_ID"]  # we'll store your sheet ID in GitHub Secrets

# === Connect to Google Sheet ===
sheet = client.open_by_key(SHEET_ID).sheet1  # first worksheet

# === Connect to Neon ===
with psycopg.connect(DB_URL) as conn:
    cur = conn.cursor()

    # Get today's date in UTC (adjust if you want US/Eastern)
    today = dt.datetime.now(dt.timezone.utc).date()

    cur.execute("""
        SELECT symbol, t, open, high, low, close, volume
        FROM ohlcv_bars
        WHERE t::date = %s
        ORDER BY symbol, t;
    """, (today,))

    rows = cur.fetchall()

# === Clear sheet ===
sheet.clear()

# === Write header ===
header = ["symbol", "timestamp_utc", "open", "high", "low", "close", "volume"]
sheet.append_row(header)

# === Write data ===
for row in rows:
    # Convert timestamp to ISO string for Sheets
    row = list(row)
    row[1] = row[1].isoformat()
    sheet.append_row(row)

print(f"[sheet_update] Wrote {len(rows)} rows to Google Sheet for {today}")
