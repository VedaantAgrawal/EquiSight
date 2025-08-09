import os
import json
import datetime as dt
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, dash_table
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import psycopg

# =================== CONFIG / ENV ===================
# Sheets (for the candlestick tab)
SA_JSON = os.environ.get("GCP_SERVICE_ACCOUNT")
SHEET_ID = os.environ.get("SHEET_ID")

# Neon (for the news tab)
RAW_DB_URL = (os.environ.get("DB_URL") or "").strip()
DB_DSN = RAW_DB_URL.replace("postgresql+psycopg://", "postgresql://") if RAW_DB_URL else ""
if DB_DSN and "sslmode=" not in DB_DSN:
    DB_DSN += ("&" if "?" in DB_DSN else "?") + "sslmode=require"

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
        # No sheet config set; return empty frame with expected columns
        return pd.DataFrame(columns=["symbol","timestamp_utc","open","high","low","close","volume"])
    ws = gc.open_by_key(SHEET_ID).sheet1
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame(columns=["symbol","timestamp_utc","open","high","low","close","volume"])
    df = pd.DataFrame(values[1:], columns=values[0])
    if df.empty:
        return df
    # Types
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Only today's UTC (belt & suspenders)
    today = pd.Timestamp.now(tz="UTC").date()
    df = df[df["timestamp_utc"].dt.date == today]
    df = df.dropna(subset=["symbol","timestamp_utc"]).sort_values(["symbol","timestamp_utc"])
    return df.reset_index(drop=True)

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

# ---------------- Neon helpers (News tab) ----------------
def load_today_news_df():
    """Pull all today_news rows (UTC day) from Neon."""
    if not DB_DSN:
        return pd.DataFrame(columns=["symbol","published_at","source","headline","summary","author","url","id"])
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT symbol, published_at, source, headline, summary, author, url, id
                FROM today_news
                WHERE published_at::date = CURRENT_DATE
                ORDER BY symbol, published_at DESC;
            """)
            rows = cur.fetchall()
            cols = [desc.name for desc in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    return df

def symbols_from_sources(sheet_df, news_df):
    """Build symbol list from either source."""
    s = set()
    if not sheet_df.empty and "symbol" in sheet_df:
        s.update(sheet_df["symbol"].dropna().unique().tolist())
    if not news_df.empty and "symbol" in news_df:
        s.update(news_df["symbol"].dropna().unique().tolist())
    return sorted(s) or ["AAPL"]

# ---------------- Dash app ----------------
app = Dash(__name__)
app.title = "OHLC + News (Live)"

# initial data & symbol list
_sheet_df = load_today_sheet_df()
_news_df  = load_today_news_df()
symbols = symbols_from_sources(_sheet_df, _news_df)

app.layout = html.Div(
    style={"maxWidth":"1200px","margin":"20px auto","fontFamily":"Inter,system-ui,Arial"},
    children=[
        html.H2("Intraday Dashboard"),
        dcc.Tabs(id="tabs", value="chart", children=[
            dcc.Tab(label="Candles", value="chart"),
            dcc.Tab(label="News (today)", value="news"),
        ]),
        html.Div(id="controls", style={"margin":"12px 0"}),
        html.Div(id="content"),
        dcc.Interval(id="tick", interval=REFRESH_MS, n_intervals=0)  # global refresh
    ]
)

# Controls (symbol dropdown) changes per tab
@app.callback(
    Output("controls", "children"),
    Input("tabs", "value"),
)
def render_controls(tab):
    return html.Div([
        html.Label("Symbol", style={"marginRight":"8px"}),
        dcc.Dropdown(
            id="symbol",
            options=[{"label": s, "value": s} for s in symbols],
            value=symbols[0],
            clearable=False,
            style={"width":"260px"}
        ),
        html.Span(id="status", style={"marginLeft":"12px","color":"#666"})
    ], style={"display":"flex","alignItems":"center","gap":"12px"})

# Content area
@app.callback(
    Output("content","children"),
    Output("status","children"),
    Input("tabs","value"),
    Input("symbol","value"),
    Input("tick","n_intervals"),
)
def render_content(tab, symbol, _n):
    if tab == "chart":
        df = load_today_sheet_df()
        if df.empty:
            fig = make_candle(pd.DataFrame(columns=df.columns), symbol if symbol else "AAPL")
            return dcc.Graph(figure=fig, config={"displaylogo": False}), "No rows for today yet."
        last_ts = df["timestamp_utc"].max()
        fig = make_candle(df, symbol)
        return dcc.Graph(figure=fig, config={"displaylogo": False}), f"Rows: {len(df)} — Last: {last_ts.strftime('%H:%M UTC')}"
    else:
        # News tab
        ndf = load_today_news_df()
        if ndf.empty:
            table = html.Div("No news rows for today yet.")
            return table, ""
        # Filter by symbol
        sdf = ndf[ndf["symbol"] == symbol].copy() if symbol else ndf.copy()
        # Pretty columns & link column
        sdf["published_at"] = pd.to_datetime(sdf["published_at"], utc=True, errors="coerce")
        sdf["time_utc"] = sdf["published_at"].dt.strftime("%H:%M")
        sdf["headline_link"] = sdf.apply(
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
            data=sdf[ [c["id"] for c in cols] ].to_dict("records"),
            columns=cols,
            page_size=20,
            sort_action="native",
            filter_action="native",
            style_table={"overflowX":"auto"},
            style_cell={"whiteSpace":"normal","height":"auto","padding":"6px"},
            style_header={"fontWeight":"600"},
        )
        status = f"Rows: {len(sdf)} — Latest: {sdf['published_at'].max().strftime('%H:%M UTC')}" if not sdf.empty else ""
        return table, status

server = app.server  # for gunicorn/Render

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.getenv("PORT","8050")), debug=True)
