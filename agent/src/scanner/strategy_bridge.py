"""Bridge between AlgoTrader strategy library and Vibe-Trading scanner.

Loads all 28 AlgoTrader strategies (70 specs across timeframes) and runs
them against OHLCV bars to generate signals with entry/stop/target.

The bridge registers AlgoTrader's `algotrader/` package as `app` in
sys.modules so the existing import statements work unchanged.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

_SCANNER_DIR = Path(__file__).parent
_ALGOTRADER_DIR = _SCANNER_DIR / "algotrader"
_APP_REGISTERED = False


def _ensure_app_registered() -> bool:
    """Register algotrader package under the 'app' alias once."""
    global _APP_REGISTERED
    if _APP_REGISTERED:
        return True
    try:
        # Add scanner dir to path so 'algotrader' is importable
        if str(_SCANNER_DIR) not in sys.path:
            sys.path.insert(0, str(_SCANNER_DIR))
        import algotrader as _at_pkg
        if "app" not in sys.modules:
            sys.modules["app"] = _at_pkg
            # Also register all sub-packages
            import importlib, pkgutil
            for info in pkgutil.walk_packages(
                path=_at_pkg.__path__,
                prefix="algotrader.",
                onerror=lambda x: None,
            ):
                alias = info.name.replace("algotrader.", "app.", 1)
                try:
                    mod = importlib.import_module(info.name)
                    if alias not in sys.modules:
                        sys.modules[alias] = mod
                except Exception:
                    pass
        _APP_REGISTERED = True
        return True
    except Exception as e:
        print(f"[strategy_bridge] Could not register AlgoTrader: {e}")
        return False


# Timeframe map: AlgoTrader spec → Vibe-Trading label
_TF_MAP = {
    "1m": "1min", "5m": "5min", "10m": "30min", "15m": "30min",
    "30m": "30min", "1h": "2hr", "2h": "2hr", "4h": "5hr",
    "1d": "multi-day", "daily": "multi-day",
}


def bars_to_dataframe(bars: list[dict]) -> pd.DataFrame:
    """Convert Alpaca bar dicts → OHLCV DataFrame for AlgoTrader."""
    rows = [{
        "open":   float(b.get("o", b.get("open", 0))),
        "high":   float(b.get("h", b.get("high", 0))),
        "low":    float(b.get("l", b.get("low", 0))),
        "close":  float(b.get("c", b.get("close", 0))),
        "volume": float(b.get("v", b.get("volume", 0))),
    } for b in bars]
    return pd.DataFrame(rows)


def run_all_strategies(symbol: str, bars: list[dict]) -> list[dict[str, Any]]:
    """Run all 28 AlgoTrader strategies (70 timeframe specs) against bars.

    Returns list of triggered signal dicts, each with:
      strategy_name, action, price, stop_loss, take_profit,
      confidence, rationale, timeframe, rr_ratio, score_contribution
    """
    if not _ensure_app_registered():
        return []

    try:
        from app.strategies import STRATEGY_REGISTRY, STRATEGY_SPECS
    except ImportError:
        return []

    df = bars_to_dataframe(bars)
    if len(df) < 20:
        return []

    signals: list[dict[str, Any]] = []
    for spec in STRATEGY_SPECS:
        try:
            cls = STRATEGY_REGISTRY.get(spec.name)
            if not cls:
                continue
            # Try instantiating with timeframe kwarg, fall back to defaults
            for kwargs in [
                {"timeframe": spec.timeframe, **spec.default_kwargs},
                {**spec.default_kwargs},
                {},
            ]:
                try:
                    strategy = cls(**kwargs)
                    break
                except TypeError:
                    continue
            else:
                continue

            sig = strategy.generate_signal(df, symbol)
            if sig is None:
                continue

            entry = float(sig.price or df["close"].iloc[-1])
            sl = float(sig.stop_loss) if sig.stop_loss else None
            tp = float(sig.take_profit) if sig.take_profit else None
            rr: float | None = None
            if sl and tp:
                risk = abs(entry - sl)
                rr = round(abs(tp - entry) / risk, 2) if risk > 0 else None

            signals.append({
                "strategy_name": spec.name,
                "strategy_style": getattr(spec, "style", ""),
                "action": sig.action.value,
                "price": round(entry, 4),
                "stop_loss": round(sl, 4) if sl else None,
                "take_profit": round(tp, 4) if tp else None,
                "confidence": sig.confidence,
                "rationale": sig.rationale,
                "timeframe": _TF_MAP.get(spec.timeframe, "multi-day"),
                "rr_ratio": rr,
                "score_contribution": round((sig.confidence or 0.5) * min(rr or 1.0, 2.5), 3),
            })
        except Exception:
            continue

    return signals


def aggregate_strategy_signals(signals: list[dict]) -> dict[str, Any]:
    """Aggregate multiple strategy signals into one unified result for the scanner."""
    if not signals:
        return {
            "triggered_count": 0, "buy_signals": [], "sell_signals": [],
            "net_score": 0.0, "consensus_action": "neutral",
            "consensus_confidence": 0.0, "best_signal": None,
            "strategy_names": [], "recommended_timeframe": "multi-day",
            "rationale_summary": "",
        }

    buys = [s for s in signals if s["action"] == "buy"]
    sells = [s for s in signals if s["action"] == "sell"]
    buy_score = sum(s["score_contribution"] for s in buys)
    sell_score = sum(s["score_contribution"] for s in sells)
    net = round(buy_score - sell_score, 3)
    consensus = "buy" if buy_score > sell_score else ("sell" if sell_score > buy_score else "neutral")
    consensus_sigs = buys if consensus == "buy" else sells
    avg_conf = (
        sum(s["confidence"] or 0.5 for s in consensus_sigs) / len(consensus_sigs)
        if consensus_sigs else 0.0
    )
    best = max(signals, key=lambda s: s["score_contribution"])
    tf = Counter(s["timeframe"] for s in (consensus_sigs or signals)).most_common(1)[0][0]
    top3 = sorted(consensus_sigs or signals, key=lambda s: s["score_contribution"], reverse=True)[:3]
    rationale = " | ".join(f"{s['strategy_name']}: {s['rationale'][:55]}" for s in top3)

    return {
        "triggered_count": len(signals),
        "buy_signals": buys,
        "sell_signals": sells,
        "net_score": net,
        "consensus_action": consensus,
        "consensus_confidence": round(avg_conf, 4),
        "best_signal": best,
        "strategy_names": [s["strategy_name"] for s in signals],
        "recommended_timeframe": tf,
        "rationale_summary": rationale,
    }
