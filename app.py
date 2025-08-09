import os
import json
import datetime as dt
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ======== ENV VARS ========
# Paste full JSON of your Google service account into GCP_SERVICE_ACCOUNT (one line).
SA_JSON = os.environ["GCP_SERVICE_ACCOUNT"]
SHEET_ID = os.environ["SHEET_ID"]            # e.g. 1j-...GpBU
REFRESH_MS = 15 * 60 * 1000                  # 15 minutes
# ==========================

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
    if not values:
        return pd.DataFrame(columns=["symbol","timestamp_utc","open","high","low","close","volume"])
    df = pd.DataFrame(values[1:], columns=values[0])  # row 1 = headers
    if df.empty:
        return df

    # Types
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Only today's UTC rows (sheet should already be “today only”, but belt & suspenders)
    today = pd.Timestamp.now(tz="UTC").date()
    df = df[df["timestamp_utc"].dt.date == today]

    # Clean/sort
    df = df.dropna(subset=["symbol","timestamp_utc"]).sort_values(
        ["symbol","timestamp_utc"]
    ).reset_index(drop=True)
    return df

def make_candle(fig_df: pd.DataFrame, symbol: str) -> go.Figure:
    # Fixed x-axis for RTH: 13:30 → 19:45 UTC
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
        xaxis=dict(
            type="date",
            range=[start, end],
            tickformat="%H:%M",
            rangeslider=dict(visible=False)
        ),
        template="plotly_white",
        hovermode="x unified",
        showlegend=False
    )
    return f

# ---- Dash app ----
app = Dash(__name__)
app.title = "OHLC Live (Google Sheet)"

# initial options from current sheet (fallback to AAPL if empty)
_init = load_today_df()
symbols = sorted(_init["symbol"].dropna().unique().tolist()) or ["AAPL"]

app.layout = html.Div(
    style={"maxWidth":"1100px","margin":"20px auto","fontFamily":"Inter,system-ui,Arial"},
    children=[
        html.H2("Intraday OHLC (15m) — Google Sheet feed"),
        html.Div([
            html.Label("Symbol", style={"marginRight":"8px"}),
            dcc.Dropdown(
                id="symbol",
                options=[{"label": s, "value": s} for s in symbols],
                value=symbols[0],
                clearable=False,
                style={"width":"260px"}
            ),
            html.Span(id="status", style={"marginLeft":"12px", "color":"#666"})
        ], style={"display":"flex","alignItems":"center","gap":"12px","marginBottom":"12px"}),
        dcc.Graph(id="chart", config={"displaylogo": False}),
        dcc.Interval(id="tick", interval=REFRESH_MS, n_intervals=0)  # auto-refresh
    ]
)

@app.callback(
    Output("chart","figure"),
    Output("status","children"),
    Input("symbol","value"),
    Input("tick","n_intervals"),
)
def refresh(symbol, _n):
    df = load_today_df()
    if df.empty:
        # Empty frame, fixed axis with message
        fig = make_candle(pd.DataFrame(columns=["symbol","timestamp_utc","open","high","low","close","volume"]), symbol)
        return fig, "No rows for today yet."
    last_ts = df["timestamp_utc"].max()
    fig = make_candle(df, symbol)
    return fig, f"Rows: {len(df)} — Last: {last_ts.strftime('%H:%M UTC')}"

server = app.server  # for gunicorn/Render
if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.getenv("PORT", "8050")), debug=True)
