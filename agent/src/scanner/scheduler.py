"""Daily scanner scheduler — runs at 9:30 AM ET (US market open).

Usage:
  python -m agent.src.scanner.scheduler          # runs once now (test mode)
  python -m agent.src.scanner.scheduler --daemon # runs daily at 09:30 ET
  python -m agent.src.scanner.scheduler --queue  # run scan + queue proposals in TAP

Environment:
  ALPACA_API_KEY / ALPACA_SECRET_KEY  — Alpaca data credentials
  TAP_PROXY_URL / TAP_AGENT_KEY       — TAP proxy for approval gating
  OPENAI_API_KEY                      — LLM for proposal generation
  SCANNER_BROKER   = etoro|alpaca     — which broker to route proposals to (default: etoro)
"""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROPOSALS_DIR = Path.home() / ".vibe-trading" / "proposals"
PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

ET = ZoneInfo("America/New_York")
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30


def _seconds_until_market_open() -> float:
    """Seconds until next 9:30 AM ET."""
    now = datetime.now(ET)
    target = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
    if now >= target:
        # Already past today's open — schedule for tomorrow
        from datetime import timedelta
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _queue_proposals_in_tap(proposals: list[dict]) -> list[str]:
    """Submit each proposal as a TAP pending transaction (routes to selected broker)."""
    import urllib.request

    tap_base = os.environ.get("TAP_PROXY_URL", "http://localhost:8081").rstrip("/")
    agent_key = os.environ.get("TAP_AGENT_KEY", "agent-dev-key")
    broker = os.environ.get("SCANNER_BROKER", "etoro")

    queued = []
    for p in proposals:
        symbol = p.get("symbol", "")
        amount = p.get("amount_usd", 100)
        rationale = p.get("rationale", "")
        confidence = p.get("confidence", "medium")

        if broker == "etoro":
            target = "https://public-api.etoro.com/api/v2/trading/execution/demo/orders"
            body = {
                "action": "open",
                "transaction": "buy",
                "orderType": "mkt",
                "leverage": 1,
                "settlementType": "cfd",
                "symbol": symbol,
                "amount": amount,
                "orderCurrency": "usd",
                "_scanner_rationale": rationale,
                "_scanner_confidence": confidence,
            }
            cred_headers = {
                "x-api-key": "<CREDENTIAL:etoro.key_id>",
                "x-user-key": "<CREDENTIAL:etoro.secret_key>",
                "User-Agent": "Mozilla/5.0 (compatible; VibeTradingBot/1.0)",
                "Accept": "application/json",
                "x-request-id": str(uuid.uuid4()),
                "Content-Type": "application/json",
            }
        else:  # alpaca
            target = "https://paper-api.alpaca.markets/v2/orders"
            body = {
                "symbol": symbol,
                "side": "buy",
                "type": "market",
                "time_in_force": "day",
                "notional": str(float(amount)),
                "client_order_id": f"scan-{uuid.uuid4().hex[:12]}",
                "_scanner_rationale": rationale,
            }
            cred_headers = {
                "APCA-API-KEY-ID": "<CREDENTIAL:alpaca.key_id>",
                "APCA-API-SECRET-KEY": "<CREDENTIAL:alpaca.secret_key>",
            }

        payload = {
            "target": target,
            "method": "POST",
            "headers": cred_headers,
            "body": body,
        }

        try:
            req = urllib.request.Request(
                tap_base + "/forward",
                data=json.dumps(payload).encode(),
                headers={"Authorization": f"Bearer {agent_key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
            txn_id = resp.get("txn_id")
            print(f"  ✅ Queued {symbol} ${amount} → TAP txn {txn_id}")
            queued.append(txn_id)
        except Exception as e:
            print(f"  ❌ Failed to queue {symbol}: {e}")

    return queued


def run_once(queue: bool = True) -> dict:
    """Run one scan cycle."""
    from src.scanner.proposals import run_scan

    print(f"\n{'='*50}")
    print(f"🔍 Daily Scanner — {datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}")
    print(f"{'='*50}")

    results = run_scan(top_n=20, max_proposals=3)

    # Save results to disk
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = PROPOSALS_DIR / f"scan_{date_str}.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\n📄 Saved scan results → {out_path}")

    # Print top candidates
    print("\n📊 Top Candidates:")
    for c in results.get("top_candidates", [])[:5]:
        sigs = " | ".join(c.get("signals", []))
        print(f"  {c['symbol']:8} score={c['score']:4.1f}  ${c['price']:.2f}  {sigs}")

    # Print proposals
    print(f"\n💡 LLM Proposals ({len(results.get('proposals', []))}):")
    for p in results.get("proposals", []):
        print(f"  [{p.get('confidence','?').upper()}] BUY {p['symbol']} ${p['amount_usd']} — {p['rationale'][:80]}")

    # Queue in TAP
    if queue and results.get("proposals"):
        print("\n🔒 Queuing proposals in TAP for your approval...")
        txn_ids = _queue_proposals_in_tap(results["proposals"])
        results["tap_txn_ids"] = txn_ids
        print(f"\n✅ {len(txn_ids)} proposals queued. Approve at: http://localhost:5899/approvals")

    return results


def daemon_loop():
    """Run as a daily daemon, firing at 9:30 AM ET each trading day."""
    print("🕐 Scanner daemon started. Waiting for market open (9:30 AM ET)...")
    while True:
        wait = _seconds_until_market_open()
        next_open = datetime.now(ET).replace(
            hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0
        )
        print(f"  Next scan: {next_open.strftime('%Y-%m-%d %H:%M ET')} (in {wait/3600:.1f}h)")
        time.sleep(wait)
        # Skip weekends
        now = datetime.now(ET)
        if now.weekday() < 5:  # Mon-Fri
            try:
                run_once(queue=True)
            except Exception as e:
                print(f"❌ Scan error: {e}")
        else:
            print(f"⏭  Weekend — skipping scan")
        time.sleep(60)  # avoid double-firing


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vibe Trading daily scanner")
    parser.add_argument("--daemon", action="store_true", help="Run as daily daemon at market open")
    parser.add_argument("--queue", action="store_true", default=True, help="Queue proposals in TAP (default: true)")
    parser.add_argument("--no-queue", action="store_false", dest="queue", help="Dry run — don't queue in TAP")
    args = parser.parse_args()

    if args.daemon:
        daemon_loop()
    else:
        run_once(queue=args.queue)
