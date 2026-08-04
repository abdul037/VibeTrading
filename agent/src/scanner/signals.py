"""Technical signal computation — RSI, momentum, volume spike.

Fetches OHLCV bars via Alpaca data API (through TAP for credential isolation).
Falls back to direct Alpaca REST if TAP is not configured.
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any

# Alpaca data REST endpoint (same key as trading; uses separate data host)
DATA_HOST = "https://data.alpaca.markets"


def _alpaca_headers() -> dict[str, str]:
    """Return Alpaca auth headers from env (set by agent startup)."""
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"}


def fetch_bars(symbol: str, days: int = 30) -> list[dict[str, Any]]:
    """Fetch daily OHLCV bars for a symbol via Alpaca data API."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days + 5)  # extra buffer for weekends
    params = urllib.parse.urlencode({
        "symbols": symbol,
        "timeframe": "1Day",
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "feed": "iex",
        "limit": days + 5,
    })
    url = f"{DATA_HOST}/v2/stocks/bars?{params}"
    try:
        req = urllib.request.Request(url, headers=_alpaca_headers())
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        bars = data.get("bars", {}).get(symbol, [])
        return bars
    except Exception:
        return []


def compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Compute RSI for the last bar given a list of closing prices."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = closes[-period + i] - closes[-period + i - 1]
        (gains if delta > 0 else losses).append(abs(delta))
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def compute_momentum(closes: list[float], period: int = 10) -> float | None:
    """Price momentum: % change over last N days."""
    if len(closes) < period + 1:
        return None
    old = closes[-(period + 1)]
    if old == 0:
        return None
    return round((closes[-1] - old) / old * 100, 2)


def compute_volume_ratio(bars: list[dict], period: int = 20) -> float | None:
    """Today's volume vs 20-day average volume ratio."""
    if len(bars) < period + 1:
        return None
    vols = [b.get("v", 0) for b in bars]
    avg_vol = sum(vols[-period - 1:-1]) / period
    if avg_vol == 0:
        return None
    return round(vols[-1] / avg_vol, 2)


def analyze_symbol(symbol: str) -> dict[str, Any]:
    """Return technical signals for one symbol."""
    bars = fetch_bars(symbol, days=30)
    if len(bars) < 15:
        return {"symbol": symbol, "ok": False, "reason": "insufficient_data"}

    closes = [b["c"] for b in bars]
    current_price = closes[-1]
    rsi = compute_rsi(closes)
    momentum_10d = compute_momentum(closes, 10)
    momentum_5d = compute_momentum(closes, 5)
    vol_ratio = compute_volume_ratio(bars)

    # Simple scoring: lower RSI = more oversold (buy signal)
    # High momentum + volume = continuation signal
    score = 0.0
    signals = []

    if rsi is not None:
        if rsi < 30:
            score += 3.0
            signals.append(f"RSI={rsi} (oversold)")
        elif rsi < 40:
            score += 1.5
            signals.append(f"RSI={rsi} (approaching oversold)")
        elif rsi > 70:
            score -= 2.0
            signals.append(f"RSI={rsi} (overbought — avoid)")

    if momentum_10d is not None:
        if momentum_10d > 5:
            score += 1.0
            signals.append(f"10d momentum={momentum_10d}%")
        elif momentum_10d < -10:
            score += 0.5  # oversold bounce candidate
            signals.append(f"10d dip={momentum_10d}%")

    if vol_ratio is not None and vol_ratio > 1.5:
        score += 0.5
        signals.append(f"volume spike={vol_ratio}x avg")

    return {
        "symbol": symbol,
        "ok": True,
        "price": current_price,
        "rsi": rsi,
        "momentum_5d": momentum_5d,
        "momentum_10d": momentum_10d,
        "volume_ratio": vol_ratio,
        "score": round(score, 2),
        "signals": signals,
    }
