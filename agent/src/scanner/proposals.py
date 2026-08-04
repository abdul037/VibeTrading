"""LLM trade proposal generator.

Takes top-scored symbols from the scanner and asks the LLM to reason about
which trades to propose. Output is structured JSON that gets queued in TAP
for human approval via the Approvals UI.
"""
from __future__ import annotations

import json
import os
from typing import Any

from src.scanner.signals import analyze_symbol
from src.scanner.watchlist import get_watchlist


def _llm_propose(top_candidates: list[dict], portfolio_summary: str = "") -> list[dict]:
    """Ask the LLM to reason over candidates and return trade proposals."""
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError:
        return _fallback_proposals(top_candidates)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    model_name = os.environ.get("LANGCHAIN_MODEL_NAME", "gpt-4o-mini")
    if not api_key:
        return _fallback_proposals(top_candidates)

    llm = ChatOpenAI(model=model_name, api_key=api_key, temperature=0.2)

    candidates_text = json.dumps(top_candidates, indent=2)
    system = """You are a quantitative trading analyst. Given technical signals (including ATR-based levels) for a list of stocks,
propose up to 3 specific trades with precise entry, stop-loss and take-profit levels.

Output ONLY valid JSON in this exact format:
[
  {
    "symbol": "AAPL",
    "action": "buy",
    "amount_usd": 200,
    "entry": 172.50,
    "stop_loss": 169.80,
    "take_profit": 178.30,
    "risk_pct": 1.56,
    "reward_pct": 3.36,
    "rr_ratio": 2.15,
    "rationale": "RSI oversold at 28, strong volume spike, price near 10d support",
    "confidence": "high",
    "brokers": ["etoro", "alpaca"]
  }
]
Rules:
- Only propose BUY trades (no shorting for now)
- Amount per trade: $100-$500 USD
- Use the pre-computed entry/stop_loss/take_profit from the levels field — adjust slightly if near support/resistance
- Only pick stocks with clear signals (RSI < 45 or strong momentum)
- confidence: "high" (RSI<30 + volume), "medium" (RSI<40), "low" (momentum only)
- brokers: always include both ["etoro", "alpaca"] unless a signal is broker-specific
- Return pure JSON array only, no markdown or explanation"""

    user = f"""Current market signals for top candidates (each includes ATR-derived entry/stop/target levels):
{candidates_text}

{f"Current portfolio context: {portfolio_summary}" if portfolio_summary else ""}

Propose up to 3 trades. Use the pre-computed 'levels' for entry/stop_loss/take_profit — refine if needed based on support/resistance."""

    try:
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        text = resp.content.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        proposals = json.loads(text)
        # Ensure brokers field is always present
        for p in proposals:
            if "brokers" not in p:
                p["brokers"] = ["etoro", "alpaca"]
        return proposals if isinstance(proposals, list) else []
    except Exception as e:
        print(f"LLM proposal error: {e}")
        return _fallback_proposals(top_candidates)


def _fallback_proposals(candidates: list[dict]) -> list[dict]:
    """Rule-based fallback when LLM is unavailable."""
    proposals = []
    for c in candidates[:3]:
        if c.get("score", 0) >= 2.0:
            levels = c.get("levels", {})
            proposals.append({
                "symbol": c["symbol"],
                "action": "buy",
                "amount_usd": 150,
                "entry": levels.get("entry", c.get("price", 0)),
                "stop_loss": levels.get("stop_loss"),
                "take_profit": levels.get("take_profit"),
                "risk_pct": levels.get("risk_pct"),
                "reward_pct": levels.get("reward_pct"),
                "rr_ratio": levels.get("rr_ratio"),
                "rationale": " | ".join(c.get("signals", ["technical signal"])),
                "confidence": "medium",
                "brokers": ["etoro", "alpaca"],
            })
    return proposals


def run_scan(top_n: int = 20, max_proposals: int = 3) -> dict[str, Any]:
    """Full scan pipeline: fetch signals → rank → LLM propose → return results.

    Args:
        top_n: How many top candidates to pass to LLM (scans all, sends top N).
        max_proposals: Max trades to propose.

    Returns:
        dict with scan_date, candidates, proposals, errors.
    """
    from datetime import datetime, timezone
    import concurrent.futures

    watchlist = get_watchlist()
    print(f"Scanning {len(watchlist)} symbols...")

    results = []
    errors = []

    # Parallel fetch — 10 workers to stay within rate limits
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(analyze_symbol, sym): sym for sym in watchlist}
        for future in concurrent.futures.as_completed(futures):
            sym = futures[future]
            try:
                r = future.result(timeout=15)
                if r.get("ok"):
                    results.append(r)
                else:
                    errors.append(sym)
            except Exception:
                errors.append(sym)

    # Rank by score descending
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    top_candidates = results[:top_n]

    print(f"Scanned {len(results)} symbols. Top candidates: {[c['symbol'] for c in top_candidates[:5]]}")

    # LLM proposals
    proposals = _llm_propose(top_candidates, portfolio_summary="")
    proposals = proposals[:max_proposals]

    return {
        "scan_date": datetime.now(timezone.utc).isoformat(),
        "universe_size": len(watchlist),
        "scanned": len(results),
        "errors": errors,
        "top_candidates": top_candidates[:10],
        "proposals": proposals,
    }
