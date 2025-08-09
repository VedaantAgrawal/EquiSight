import os
import re
import json
import datetime as dt
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State, no_update
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ======== ENV VARS ========
SA_JSON = os.environ["GCP_SERVICE_ACCOUNT"]
SHEET_ID = os.environ["SHEET_ID"]                  # OHLCV sheet (Sheet1)
SHEET_ID_NEWS = os.environ.get("SHEET_ID_NEWS")    # News sheet (separate file)
NEWS_SHEET_TAB = os.environ.get("NEWS_SHEET_TAB", "Sheet1")
REFRESH_MS = 15 * 60 * 1000  # 15 minutes

TRACKED_SYMBOLS = sorted([
    s.strip().upper()
    for s in os.environ.get("SYMBOLS","").split(",")
    if s.strip()
])

# -------- gspread helpers --------
def _normalize_sheet_id(raw: str) -> str:
    if not raw:
        return ""
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", raw)
    return m.group(1) if m else raw.strip()

def gs_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(SA_JSON), scopes)
    return gspread.authorize(creds)

# -------- OHLCV (Sheet_ID) --------
def load_today_df():
    gc = gs_client()
    ws = gc.open_by_key(SHEET_ID).sheet1
    values = ws.get_all_values()
    if not values or len(values) < 2:
        return pd.DataFrame(columns=["symbol","timestamp_utc","open","high","low","close","volume"])
    df = pd.DataFrame(values[1:], columns=values[0])

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    today = pd.Timestamp.now(tz="UTC").date()
    df = df[df["timestamp_utc"].dt.date == today]
    df = df.dropna(subset=["symbol","timestamp_utc"]).sort_values(["symbol","timestamp_utc"]).reset_index(drop=True)
    return df

def load_sheet_symbols():
    try:
        gc = gs_client()
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

def dropdown_options():
    syms = set(TRACKED_SYMBOLS)
    syms.update(load_sheet_symbols())
    if not syms:
        syms = {"AAPL"}
    opts = [{"label": s, "value": s} for s in sorted(syms)]
    return opts

def make_candle(fig_df: pd.DataFrame, symbol: str) -> go.Figure:
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

# -------- News (SHEET_ID_NEWS) --------
def load_today_news_df():
    if not SHEET_ID_NEWS:
        return pd.DataFrame(columns=["symbol","published_at","source","headline","summary","author","url","id"])
    gc = gs_client()
    sid = _normalize_sheet_id(SHEET_ID_NEWS)
    sh = gc.open_by_key(sid)
    try:
        ws = sh.worksheet(NEWS_SHEET_TAB)
    except gspread.WorksheetNotFound:
        # try first sheet as fallback
        ws = sh.sheet1
    values = ws.get_all_values()
    if not values or len(values) < 2:
        return pd.DataFrame(columns=["symbol","published_at","source","headline","summary","author","url","id"])
    df = pd.DataFrame(values[1:], columns=values[0])

    # coerce types
    if "published_at" in df.columns:
        df["published_at"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
    for col in ["symbol","source","headline","summary","author","url","id"]:
        if col not in df.columns:
            df[col] = None

    today = pd.Timestamp.now(tz="UTC").date()
    if "published_at" in df.columns:
        df = df[df["published_at"].dt.date == today]

    df["symbol"] = df["symbol"].str.upper()
    df = df.dropna(subset=["symbol","published_at"]).sort_values(["symbol","published_at"], ascending=[True, False]).reset_index(drop=True)
    return df

def news_cards(df: pd.DataFrame, symbol: str):
    sdf = df[df["symbol"] == symbol] if not df.empty else pd.DataFrame()
    if sdf.empty:
        return html.Div("No news for today yet.", style={"color":"#666","marginTop":"8px"})

    items = []
    for _, r in sdf.iterrows():
        ts = r["published_at"]
        time_str = ts.strftime("%H:%M UTC") if pd.notna(ts) else ""
        meta_bits = [b for b in [r.get("author"), time_str, r.get("source")] if b]
        meta = " · ".join(meta_bits)
        url = r.get("url")
        headline_el = html.A(r.get("headline",""), href=url, target="_blank", style={"fontWeight":"600","textDecoration":"none","color":"#1a73e8"}) if url else html.Div(r.get("headline",""), style={"fontWeight":"600"})
        items.append(
            html.Div([
                headline_el,
                html.Div(r.get("summary",""), style={"fontSize":"13px","color":"#333","marginTop":"4px"}),
                html.Div(meta, style={"fontSize":"11px","color":"#777","marginTop":"4px","wordWrap":"break-word"}),
            ], style={"padding":"10px 0","borderBottom":"1px solid #eee"})
        )
    return html.Div(items)

# ---- Dash app ----
app = Dash(__name__)
app.title = "OHLC + News (Google Sheets)"

initial_opts = dropdown_options()
initial_val = initial_opts[0]["value"] if initial_opts else "AAPL"

app.layout = html.Div(
    style={"maxWidth":"1100px","margin":"20px auto","fontFamily":"Inter,system-ui,Arial"},
    children=[
        html.H2("Intraday OHLC (15m) — Google Sheet feed"),
        html.Div([
            html.Label("Symbol", style={"marginRight":"8px"}),
            dcc.Dropdown(
                id="symbol",
                options=initial_opts,
                value=initial_val,
                clearable=False,
                style={"width":"260px"}
            ),
            html.Span(id="status", style={"marginLeft":"12px", "color":"#666"})
        ], style={"display":"flex","alignItems":"center","gap":"12px","marginBottom":"12px"}),

        dcc.Graph(id="chart", config={"displaylogo": False}),
        html.Hr(),
        html.H3("News (today)"),
        html.Div(id="news-list"),

        dcc.Interval(id="tick", interval=REFRESH_MS, n_intervals=0)
    ]
)

# Refresh dropdown options and keep value valid
@app.callback(
    Output("symbol", "options"),
    Output("symbol", "value"),
    Input("tick", "n_intervals"),
    State("symbol", "value"),
)
def refresh_dropdown(_n, current_value):
    opts = dropdown_options()
    values = [o["value"] for o in opts]
    if current_value in values:
        return opts, current_value
    return opts, (values[0] if values else "AAPL")

# Update chart + status
@app.callback(
    Output("chart","figure"),
    Output("status","children"),
    Input("symbol","value"),
    Input("tick","n_intervals"),
)
def refresh_chart(symbol, _n):
    df = load_today_df()
    if df.empty:
        fig = make_candle(pd.DataFrame(columns=["symbol","timestamp_utc","open","high","low","close","volume"]), symbol or "AAPL")
        return fig, "No rows for today yet."
    last_ts = df["timestamp_utc"].max()
    fig = make_candle(df, symbol or "AAPL")
    return fig, f"Rows: {len(df)} — Last: {last_ts.strftime('%H:%M UTC')}"

# Update news
@app.callback(
    Output("news-list","children"),
    Input("symbol","value"),
    Input("tick","n_intervals"),
)
def refresh_news(symbol, _n):
    ndf = load_today_news_df()
    return news_cards(ndf, symbol or "AAPL")

server = app.server
if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.getenv("PORT", "8050")), debug=True)
