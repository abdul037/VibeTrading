"""S&P 500 symbol list (top 100 by liquidity for fast scanning).

Full S&P 500 list is fetched dynamically from Wikipedia when USE_FULL_SP500=true.
Default is a curated top-100 list covering most major sectors.
"""
from __future__ import annotations
import os

TOP_100_SP500 = [
    # Tech
    "AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","AVGO","AMD","ORCL",
    "CRM","INTC","QCOM","TXN","MU","AMAT","KLAC","LRCX","MRVL","ADBE",
    # Finance
    "BRK.B","JPM","V","MA","BAC","WFC","GS","MS","AXP","BLK",
    "C","SCHW","USB","PNC","TFC",
    # Healthcare
    "LLY","UNH","JNJ","ABBV","MRK","PFE","TMO","ABT","DHR","BMY",
    "AMGN","GILD","VRTX","REGN","ISRG",
    # Consumer
    "COST","WMT","PG","KO","PEP","MCD","SBUX","NKE","TGT","HD",
    "LOW","AMZN","TJX","ROST","DG",
    # Energy
    "XOM","CVX","COP","SLB","EOG","PSX","VLO","MPC","OXY","HAL",
    # Industrials
    "CAT","DE","HON","UPS","FDX","RTX","LMT","GE","BA","MMM",
    # ETFs (broad market proxies)
    "SPY","QQQ","IWM","DIA","XLK","XLF","XLV","XLE","XLI",
    # Crypto proxies
    "COIN","MSTR","MARA","RIOT",
]

def get_watchlist() -> list[str]:
    """Return the scan universe. Fetches full S&P 500 if USE_FULL_SP500=true."""
    if os.environ.get("USE_FULL_SP500", "").lower() == "true":
        try:
            return _fetch_sp500_wikipedia()
        except Exception:
            pass
    return TOP_100_SP500

def _fetch_sp500_wikipedia() -> list[str]:
    import urllib.request, re
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    with urllib.request.urlopen(url, timeout=10) as r:
        html = r.read().decode()
    tickers = re.findall(r'<td><a[^>]*>([A-Z]{1,5})</a></td>', html)
    return list(dict.fromkeys(tickers))[:500]  # dedupe, cap at 500
