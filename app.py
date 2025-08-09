import os
import json
import datetime as dt
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State, no_update
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ======== ENV VARS ========
SA_JSON = os.environ["GCP_SERVICE_ACCOUNT"]
SHEET_ID = os.environ["SHEET_ID"]
REFRESH_MS = 15 * 60 * 1000  # 15 minutes

TRACKED_SYMBOLS = sorted([
    s.strip().upper()
    for s in os.environ.get("SYMBOLS","").split(",")
    if s.strip()
])

def gs_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(SA_JSON), scopes)
    return gspread.authorize(creds)

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
    """All distinct symbols from the sheet (no date filter)."""
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
    print(f"[dropdown] {', '.join([o['value'] for o in opts])}")
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

# ---- Dash app ----
app = Dash(__name__)
app.title = "OHLC Live (Google Sheet)"

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

@app.callback(
    Output("chart","figure"),
    Output("status","children"),
    Input("symbol","value"),
    Input("tick","n_intervals"),
)
def refresh(symbol, _n):
    df = load_today_df()
    if df.empty:
        fig = make_candle(pd.DataFrame(columns=["symbol","timestamp_utc","open","high","low","close","volume"]), symbol or "AAPL")
        return fig, "No rows for today yet."
    last_ts = df["timestamp_utc"].max()
    fig = make_candle(df, symbol or "AAPL")
    return fig, f"Rows: {len(df)} — Last: {last_ts.strftime('%H:%M UTC')}"

server = app.server
if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.getenv("PORT", "8050")), debug=True)
