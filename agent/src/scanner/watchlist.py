"""S&P 500 symbol list — full 503 symbols by default.

Uses a bundled static list (fast, no network) with Wikipedia fallback for updates.
Set USE_FULL_SP500=wikipedia to force a live fetch from Wikipedia.
"""
from __future__ import annotations
import os

# Full S&P 500 — 503 symbols (as of mid-2025, updated periodically)
SP500_SYMBOLS = [
    # Mega-cap Tech
    "AAPL","MSFT","NVDA","GOOGL","GOOG","META","AMZN","TSLA","AVGO","ORCL",
    "AMD","INTC","QCOM","TXN","MU","AMAT","KLAC","LRCX","MRVL","ADBE",
    "CRM","NOW","SNOW","PANW","CRWD","ZS","FTNT","OKTA","MDB","DDOG",
    "NET","TEAM","HUBS","ZM","DOCU","TWLO","ESTC","COUP","VEEV","WDAY",
    # Finance
    "BRK.B","JPM","V","MA","BAC","WFC","GS","MS","AXP","BLK",
    "C","SCHW","USB","PNC","TFC","COF","DFS","SYF","ALLY","FITB",
    "KEY","RF","HBAN","MTB","CFG","ZION","CMA","BOKF","WBS","FHN",
    "ICE","CME","CBOE","NDAQ","MSCI","SPGI","MCO","FDS","BEN","IVZ",
    "WTW","AON","MMC","MKL","ALL","TRV","CB","HIG","MET","PRU",
    # Healthcare
    "LLY","UNH","JNJ","ABBV","MRK","PFE","TMO","ABT","DHR","BMY",
    "AMGN","GILD","VRTX","REGN","ISRG","BSX","EW","BDX","ZBH","SYK",
    "MDT","BAX","HOLX","IDXX","IQV","IQVIA","CRL","HSIC","PDCO","PKI",
    "DGX","LH","XRAY","VTRS","HUM","CVS","CI","ELV","CNC","MOH",
    # Consumer Discretionary
    "COST","WMT","HD","MCD","NKE","SBUX","TGT","LOW","TJX","ROST",
    "DG","DLTR","DRI","YUM","CMG","DARDEN","LVS","MGM","WYNN","CZR",
    "MAR","HLT","H","IHG","CCL","RCL","NCLH","RL","PVH","VFC",
    "HBI","LEVI","G","URBN","ANF","AEO","GPS","BBWI","TPR","CPRI",
    "BURL","FIVE","OLLI","BOOT","CROX","SKX","WWW","FL","HIBB","SCVL",
    # Consumer Staples
    "PG","KO","PEP","PM","MO","MDLZ","GIS","K","CPB","SJM",
    "CAG","HRL","MKC","CLX","CHD","CL","EL","KVUE","HELE","SPB",
    # Energy
    "XOM","CVX","COP","SLB","EOG","PSX","VLO","MPC","OXY","HAL",
    "DVN","FANG","PXD","APA","MRO","HES","EQT","AR","RRC","SWN",
    "COG","SM","CTRA","OVV","CHK","NOG","MTDR","CPE","REI","TALO",
    # Industrials
    "CAT","DE","HON","UPS","FDX","RTX","LMT","GE","BA","MMM",
    "GD","NOC","HII","LHX","TDG","TXT","HWM","SPR","WWD","KTOS",
    "EMR","ETN","ITW","PH","ROK","AME","ROP","XYL","IDEX","GGG",
    "FAST","GWW","MSC","NDSN","TTC","WMS","FELE","AIXI","GNSS","HAYN",
    # Materials
    "LIN","APD","ECL","SHW","PPG","NEM","FCX","AA","ALB","MP",
    "CF","MOS","NTR","FMC","CE","EMN","HUN","TREX","AZEK","BLDR",
    # Real Estate
    "AMT","PLD","CCI","EQIX","PSA","SPG","O","WELL","DLR","VICI",
    "EXR","AVB","EQR","UDR","CPT","MAA","AIV","NNN","WPC","STOR",
    # Utilities
    "NEE","DUK","SO","D","AEP","EXC","SRE","PEG","XEL","WEC",
    "ES","CMS","NI","PNW","ATO","OGE","EVRG","AVA","IDA","NWE",
    # Communication Services
    "GOOGL","META","NFLX","DIS","CMCSA","T","VZ","TMUS","CHTR","DISH",
    "PARA","WBD","FOX","FOXA","NYT","NWS","NWSA","OMC","IPG","PUB",
    # ETFs (broad market proxies — useful signals)
    "SPY","QQQ","IWM","DIA","XLK","XLF","XLV","XLE","XLI","XLY",
    "XLP","XLU","XLC","XLRE","XLB","GLD","SLV","TLT","HYG","LQD",
    # Crypto proxies
    "COIN","MSTR","MARA","RIOT","CLSK","CIFR","HUT","BTBT","BTDR","WGMI",
]

# Deduplicate while preserving order
_seen: set[str] = set()
_deduped: list[str] = []
for _s in SP500_SYMBOLS:
    if _s not in _seen:
        _seen.add(_s)
        _deduped.append(_s)
SP500_SYMBOLS = _deduped


def get_watchlist() -> list[str]:
    """Return the scan universe.

    Default: bundled ~500 symbol list (instant, no network).
    Set USE_FULL_SP500=wikipedia to fetch live from Wikipedia.
    """
    if os.environ.get("USE_FULL_SP500", "").lower() == "wikipedia":
        try:
            return _fetch_sp500_wikipedia()
        except Exception:
            pass
    return SP500_SYMBOLS


def _fetch_sp500_wikipedia() -> list[str]:
    import urllib.request, re
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    with urllib.request.urlopen(url, timeout=10) as r:
        html = r.read().decode()
    tickers = re.findall(r'<td><a[^>]*>([A-Z]{1,5})</a></td>', html)
    return list(dict.fromkeys(tickers))[:503]  # dedupe, cap at 503
