"""
Universe of equities used for the ARIMA-vs-gradient-boosted forecasting
comparison. Diversified across sectors and liquid enough to have clean,
complete daily price history going back 5+ years.
"""

SYMBOLS = [
    # Technology
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "ORCL", "CRM",
    "ADBE", "CSCO", "INTC", "AMD", "TXN", "QCOM", "IBM", "NOW", "INTU",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP", "BLK", "SCHW",
    # Healthcare
    "JNJ", "UNH", "PFE", "MRK", "ABBV", "LLY", "TMO", "ABT", "DHR",
    # Consumer
    "WMT", "PG", "KO", "PEP", "COST", "MCD", "NKE", "HD", "SBUX", "TGT",
    # Industrials / Energy
    "XOM", "CVX", "BA", "CAT", "GE", "HON", "UPS", "LMT",
    # Communication / Media
    "DIS", "NFLX", "CMCSA", "VZ", "T",
]
