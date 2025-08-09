import os
import json
import datetime as dt
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State, dash_table

import gspread
from oauth2client.service_account import ServiceAccountCredentials
import psycopg

# =================== CONFIG / ENV ===================
SA_JSON = os.environ.get("GCP_SERVICE_ACCOUNT")   # full JSON string
SHEET_ID = os.environ.get("SHEET_ID")             # your sheet id

RAW_DB_URL = (os.environ.get("DB_URL") or "").strip()
DB_DSN = RAW_DB_URL.replace("postgresql+psycopg://", "postgresql://") if RAW_DB_URL else ""
if DB_DSN and "sslmode=" not in DB_DSN:
    DB_DSN += ("&" if "?" in DB_DSN else "?") + "sslmode=require"

TRACKED_SYMBOLS = sorted([
    s.strip().upper()
    for s in (os.environ.get("SYMBOLS", "")).split(",")
    if s.strip()
])

print("[boot] TRACKED_SYMBOLS:", TRACKED_SYMBOLS)
print("[boot] SHEET_ID set:", bool(SHEET_ID), "DB_DSN set:", bool(DB_DSN))

REFRESH_MS = 15 * 60 * 1000  # 15 minutes
# ====================================================

# ---------------- Google Sheets helpers (Chart tab) ----------------
def gs_client():
    if not SA_JSON or not SHEET_ID:
        return None
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(SA_JSON), scopes)
    return gspread.authorize(creds)

def load_today_sheet_df():
    gc = gs_client()
    if not gc:
        return pd.DataFrame(columns=["symbol","timestamp_utc","open","high","low","close","volume"])
    try:
        ws = gc.open_by_key(SHEET_ID).sheet1
        values = ws.get_all_values()
    except Exception as e:
        print(f"[warn] Sheets access failed: {e}")
        return pd.DataFrame(columns=["symbol","timestamp_utc","open","high","low","close","volume"])

    if not values:
        return pd.DataFrame(columns=["symbol","timestamp_utc","open","high","low","close","volume"])

    df = pd.DataFrame(values[1:], columns=values[0])
    if df.empty:
        return df

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    today = pd.Timestamp.now(tz="UTC").date()
    df = df[df["timestamp_utc"].dt.date == today]
    df = df.dropna(subset=["symbol","timestamp_utc"]).sort_values(["symbol","timestamp_utc"])
    return df.reset_index(drop=True)

def load_sheet_symbols():
    """All distinct symbols from the sheet (no date filter)."""
    gc = gs_client()
    if not gc:
        return []
    try:
        ws = gc.open_by_key(SHEET_ID).sheet1
        values = ws.get_all_values()
        if not values or len(values) < 2:
            return []
        df_all = pd.DataFrame(values[1:], columns=values[0])
        if "symbol" not in df_all.columns:
            return []
        return sorted(df_all["symbol"].dropna().str.upper().unique().tolist())
    except Exception as e:
        print(f"[warn] load_sheet_symbols failed: {e}")
        return []

def make_candle(fig_df: pd.DataFrame, symbol: str) -> go.Figure:
    # Fixed UTC RTH window 13:30 → 19:45
    today = pd.Timestamp.now(tz="UTC").date()
    start = pd.Timestamp.combine(today, dt.time(13, 30, tzinfo=dt.timezone.utc))
    end   = pd.Timestamp.combine(today, dt.time(19, 45, tzinfo=dt.timezone.utc))

    f = go.Figure()
    sdf = fig_df[fig_df["symbol"] == symbol]
    if not sdf.empty:
        f.add_trace(go.Candlestick(
            x=sdf["timestamp_utc"],
            open=sdf["open"],
            high=sdf["high"],
            low=sdf["low"],
            close=sdf["close"],
            name=symbol
        ))
    f.update_layout(
        title=f"{symbol} — 15m OHLC (UTC)",
        margin=dict(l=30, r=20, t=40, b=40),
        xaxis_title="Time (UTC)",
        yaxis_title="Price",
        xaxis=dict(type="date", range=[start, end], tickformat="%H:%M",
                   rangeslider=dict(visible=False)),
        template="plotly_white",
        hovermode="x unified",
        showlegend=False
    )
    return f

# ---------------- Neon helpers (NEWS from backfill table) ----------------
def load_news_df(start_date, end_date):
    """
    Pull rows from persistent `news` table between start_date and end_date (inclusive).
    Dates must be datetime.date objects in UTC context.
    """
    if not DB_DSN:
        return pd.DataFrame(columns=["symbol","published_at","source","headline","summary","author","url","id"])
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT symbol, published_at, source, headline, summary, author, url, id
                FROM news
                WHERE published_at::date BETWEEN %s AND %s
                ORDER BY symbol, published_at DESC;
            """, (start_date, end_date))
            rows = cur.fetchall()
            cols = [desc.name for desc in cur.description]
    return pd.DataFrame(rows, columns=cols)

def news_distinct_symbols():
    """Distinct symbols present in `news` (no date filter)."""
    if not DB_DSN:
        return []
    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT symbol FROM news;")
                return sorted([r[0] for r in cur.fetchall() if r and r[0]])
    except Exception as e:
        print(f"[warn] news_distinct_symbols failed: {e}")
        return []

def dropdown_options():
    # start with env-tracked symbols
    syms = set(TRACKED_SYMBOLS)
    # add all symbols present anywhere in the sheet
    syms.update(load_sheet_symbols())
    # add any symbols seen in the backfill news table
    syms.update(news_distinct_symbols())
    if not syms:
        syms = {"AAPL"}
    opts = [{"label": s, "value": s} for s in sorted(syms)]
    print(f"[dropdown] options: {', '.join([o['value'] for o in opts])}")
    return opts

# ---------------- Dash app ----------------
app = Dash(__name__)
app.title = "OHLC + News (Live)"

_today = pd.Timestamp.now(tz="UTC").date()
initial_options = dropdown_options()
initial_symbol = (TRACKED_SYMBOLS[0] if TRACKED_SYMBOLS else (initial_options[0]["value"] if initial_options else "AAPL"))

app.layout = html.Div(
    style={"maxWidth":"1200px","margin":"20px auto","fontFamily":"Inter,system-ui,Arial"},
    children=[
        html.H2("Intraday Dashboard"),
        dcc.Tabs(id="tabs", value="chart", children=[
            dcc.Tab(label="Candles", value="chart"),
            dcc.Tab(label="News (from backfill)", value="news"),
        ]),

        # Controls (symbol + date range for news)
        html.Div(id="controls", style={"display":"flex","alignItems":"center","gap":"12px","margin":"12px 0"}, children=[
            html.Label("Symbol"),
            dcc.Dropdown(
                id="symbol",
                options=initial_options,
                value=initial_symbol,
                clearable=False,
                style={"width":"260px"}
            ),
            html.Div(id="news-date-controls"),  # date picker appears only on News tab
            html.Span(id="status", style={"marginLeft":"8px","color":"#666"})
        ]),

        html.Div(id="content"),
        dcc.Interval(id="tick", interval=REFRESH_MS, n_intervals=0)  # global refresh
    ]
)

# Show date picker only on News tab
@app.callback(
    Output("news-date-controls", "children"),
    Input("tabs", "value"),
)
def show_date_controls(tab):
    if tab != "news":
        return ""
    return html.Div(style={"display":"flex","alignItems":"center","gap":"8px"}, children=[
        html.Label("Date range (UTC)"),
        dcc.DatePickerRange(
            id="date_range",
            start_date=str(_today),
            end_date=str(_today),
            display_format="YYYY-MM-DD",
            minimum_nights=0,
            clearable=True
        )
    ])

# Keep dropdown options fresh and ensure value is valid
@app.callback(
    Output("symbol", "options"),
    Output("symbol", "value"),
    Input("tabs", "value"),        # fire once at startup too
    Input("tick", "n_intervals"),
    State("symbol", "value"),
)
def refresh_dropdown(_tab, _n, current_value):
    opts = dropdown_options()
    values = [o["value"] for o in opts]
    if current_value in values:
        return opts, current_value
    new_value = values[0] if values else "AAPL"
    return opts, new_value

# Content switcher
@app.callback(
    Output("content","children"),
    Output("status","children"),
    Input("tabs","value"),
    Input("symbol","value"),
    Input("tick","n_intervals"),
    State("date_range", "start_date"),
    State("date_range", "end_date"),
)
def render_content(tab, symbol, _n, start_date, end_date):
    if tab == "chart":
        df = load_today_sheet_df()
        if df.empty:
            fig = make_candle(pd.DataFrame(columns=["symbol","timestamp_utc","open","high","low","close","volume"]), symbol or "AAPL")
            return dcc.Graph(figure=fig, config={"displaylogo": False}), "No rows for today yet."
        last_ts = df["timestamp_utc"].max()
        fig = make_candle(df, symbol)
        return dcc.Graph(figure=fig, config={"displaylogo": False}), f"Rows: {len(df)} — Last: {last_ts.strftime('%H:%M UTC')}"

    # News tab
    try:
        s_date = pd.to_datetime(start_date).date() if start_date else _today
        e_date = pd.to_datetime(end_date).date() if end_date else _today
    except Exception:
        s_date, e_date = _today, _today

    ndf = load_news_df(s_date, e_date)
    if symbol:
        ndf = ndf[ndf["symbol"] == symbol].copy()
    if ndf.empty:
        return html.Div(f"No news rows for {symbol or 'selected symbols'} between {s_date} and {e_date}."), ""

    ndf["published_at"] = pd.to_datetime(ndf["published_at"], utc=True, errors="coerce")
    ndf["time_utc"] = ndf["published_at"].dt.strftime("%Y-%m-%d %H:%M")
    ndf["headline_link"] = ndf.apply(
        lambda r: f"[{r['headline']}]({r['url']})" if pd.notna(r.get("url")) and pd.notna(r.get("headline")) else (r.get("headline") or ""),
        axis=1
    )
    cols = [
        {"name":"Time (UTC)", "id":"time_utc"},
        {"name":"Source",     "id":"source"},
        {"name":"Headline",   "id":"headline_link", "presentation":"markdown"},
        {"name":"Summary",    "id":"summary"},
        {"name":"Author",     "id":"author"},
        {"name":"URL",        "id":"url"},
        {"name":"ID",         "id":"id"},
    ]
    table = dash_table.DataTable(
        data=ndf[[c["id"] for c in cols]].to_dict("records"),
        columns=cols,
        page_size=20,
        sort_action="native",
        filter_action="native",
        style_table={"overflowX":"auto"},
        style_cell={"whiteSpace":"normal","height":"auto","padding":"6px"},
        style_header={"fontWeight":"600"},
    )
    status = f"Rows: {len(ndf)} — Latest: {ndf['published_at'].max().strftime('%Y-%m-%d %H:%M UTC')}"
    return table, status

server = app.server  # for gunicorn/Render

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.getenv("PORT","8050")), debug=True)
