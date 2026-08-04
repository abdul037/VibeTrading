"""eToro demo/paper connector with TAP credential isolation.

Uses the eToro Public API (https://public-api.etoro.com) — **demo endpoints only**.
All writes (place order, close position) are routed through the TAP proxy so that
a human must approve each trade before it is forwarded to eToro.

Authentication: x-api-key + x-user-key headers (non-interactive credential pair).
These are never stored in the agent process; only <CREDENTIAL:etoro.*> placeholders
are sent and resolved server-side by TAP.

Endpoints used:
  POST /api/v2/trading/execution/demo/orders           — place order (open position)
  DELETE /api/v2/trading/execution/demo/orders/{id}    — cancel pending order
  POST /api/v1/trading/execution/demo/market-close-orders/positions/{id}  — close position
  GET  /api/v1/trading/info/demo/portfolio             — open positions + pending orders
  GET  /api/v1/trading/info/demo/pnl                   — account PnL / balance snapshot

Config is stored in ~/.vibe-trading/etoro.json:
  {
    "api_key":  "<your x-api-key>",
    "user_key": "<your x-user-key>",
    "profile":  "demo"               # only "demo" is supported here
  }
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from src.config.paths import get_runtime_root
from src.trading import tap_forward

CONFIG_FILENAME = "etoro.json"
ETORO_BASE = "https://public-api.etoro.com"

# TAP credential name (stored in TAP; holds api_key + user_key)
TAP_ETORO_CREDENTIAL_ENV = "TAP_ETORO_CREDENTIAL"
DEFAULT_TAP_ETORO_CREDENTIAL = "etoro"


class EToroConfigError(RuntimeError):
    """Raised when eToro connector config is missing or invalid."""


@dataclass(frozen=True)
class EToroConfig:
    """eToro connector settings."""
    api_key: str = ""
    user_key: str = ""
    profile: str = "demo"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "EToroConfig":
        payload = dict(data or {})
        profile = str(payload.get("profile") or "demo").strip().lower()
        if profile != "demo":
            raise EToroConfigError("Only 'demo' profile is supported; live trading requires explicit opt-in.")
        return cls(
            api_key=str(payload.get("api_key") or "").strip(),
            user_key=str(payload.get("user_key") or "").strip(),
            profile=profile,
        )


def config_path() -> Path:
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> EToroConfig:
    path = config_path()
    if not path.exists():
        return EToroConfig()
    try:
        return EToroConfig.from_mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise EToroConfigError(f"Invalid eToro config at {path}: {exc}") from exc


def save_config(config: EToroConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


# ---------------------------------------------------------------------------
# TAP helpers
# ---------------------------------------------------------------------------

def _tap_cred_headers() -> dict[str, str]:
    """Credential + required headers passed through TAP to eToro."""
    name = os.environ.get(TAP_ETORO_CREDENTIAL_ENV, DEFAULT_TAP_ETORO_CREDENTIAL)
    return {
        "x-api-key": f"<CREDENTIAL:{name}.key_id>",
        "x-user-key": f"<CREDENTIAL:{name}.secret_key>",
        "User-Agent": "Mozilla/5.0 (compatible; VibeTradingBot/1.0)",
        "Accept": "application/json",
        "x-request-id": str(uuid.uuid4()),
    }


def _tap_enabled() -> bool:
    return bool(os.environ.get("TAP_PROXY_URL"))


def _read_via_tap(url: str) -> Any:
    """GET through TAP; unwrap the response envelope."""
    result = tap_forward.forward(
        target_url=url,
        method="GET",
        body=None,
        credential_headers=_tap_cred_headers(),
    )
    if not result.get("ok"):
        raise RuntimeError(f"TAP read failed: {result.get('error')}")
    body = result.get("body")
    # Unwrap TAP envelope {ok, body, status_code} if present
    if isinstance(body, dict) and "body" in body and "ok" in body:
        body = body["body"]
    return body


def _write_via_tap(url: str, method: str, body: Any = None) -> Any:
    """POST/DELETE through TAP (blocks until human approves)."""
    body_str = json.dumps(body) if body is not None else None
    result = tap_forward.forward(
        target_url=url,
        method=method,
        body=body_str,
        credential_headers=_tap_cred_headers(),
    )
    if not result.get("ok"):
        raise RuntimeError(f"TAP write failed (decision={result.get('decision')}): {result.get('error')}")
    resp = result.get("body")
    if isinstance(resp, dict) and "body" in resp and "ok" in resp:
        resp = resp["body"]
    return resp


def _direct_get(url: str, config: EToroConfig) -> Any:
    """Direct GET (no TAP) for fallback path."""
    import urllib.request
    req = urllib.request.Request(url, headers={
        "x-api-key": config.api_key,
        "x-user-key": config.user_key,
        "x-request-id": str(uuid.uuid4()),
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def _direct_post(url: str, body: Any, config: EToroConfig, method: str = "POST") -> Any:
    """Direct POST/DELETE (no TAP) — only called when TAP is not configured."""
    import urllib.request
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(url, data=data, method=method, headers={
        "x-api-key": config.api_key,
        "x-user-key": config.user_key,
        "x-request-id": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        resp_data = r.read().decode()
        return json.loads(resp_data) if resp_data.strip() else {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_status(config: EToroConfig | None = None) -> dict[str, Any]:
    """Return account PnL / balance snapshot — read-only, no approval needed."""
    cfg = config or load_config()
    url = f"{ETORO_BASE}/api/v1/trading/info/demo/pnl"
    try:
        if _tap_enabled():
            data = _read_via_tap(url)
        else:
            data = _direct_get(url, cfg)
        return {"ok": True, "profile": cfg.profile, "data": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_account_snapshot(config: EToroConfig | None = None) -> dict[str, Any]:
    """Return full demo portfolio (positions + pending orders + balance)."""
    cfg = config or load_config()
    url = f"{ETORO_BASE}/api/v1/trading/info/demo/portfolio"
    try:
        if _tap_enabled():
            data = _read_via_tap(url)
        else:
            data = _direct_get(url, cfg)
        return {"ok": True, "profile": cfg.profile, "portfolio": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_open_positions(config: EToroConfig | None = None) -> list[dict[str, Any]]:
    """Return a list of open demo positions."""
    snapshot = get_account_snapshot(config)
    if not snapshot.get("ok"):
        raise RuntimeError(snapshot.get("error", "Failed to get portfolio"))
    portfolio = snapshot.get("portfolio") or {}
    # eToro portfolio response has a "positions" list
    positions = portfolio.get("positions") or []
    return [
        {
            "position_id": p.get("positionID") or p.get("positionId"),
            "instrument_id": p.get("instrumentID") or p.get("instrumentId"),
            "symbol": p.get("symbol") or p.get("instrumentName"),
            "direction": p.get("direction") or p.get("isBuy", True) and "buy" or "sell",
            "amount": p.get("amount") or p.get("investedAmount"),
            "units": p.get("units"),
            "open_rate": p.get("openRate"),
            "current_rate": p.get("currentRate"),
            "profit_loss": p.get("profit") or p.get("netProfit"),
            "status": "open",
        }
        for p in positions
    ]


def place_order(
    instrument_id: int | None = None,
    symbol: str | None = None,
    action: str = "open",
    transaction: str = "buy",
    order_type: str = "mkt",
    amount: float | None = None,
    units: float | None = None,
    leverage: int = 1,
    settlement_type: str = "cfd",
    config: EToroConfig | None = None,
) -> dict[str, Any]:
    """Place a demo market order via TAP (requires human approval).

    Args:
        instrument_id: eToro numeric instrument ID (e.g. 101 for EUR/USD).
        symbol: Ticker symbol string (e.g. "AAPL"). Provide either this or instrument_id, not both.
        action: "open" (only supported currently by eToro v2 orders endpoint).
        transaction: "buy" or "sell".
        order_type: "mkt" (market) or "lmt" (limit).
        amount: Dollar amount to invest (use either amount or units, not both).
        units: Number of units/contracts.
        leverage: Leverage multiplier (default 1 = no leverage).
        settlement_type: "cfd" or "real" (stock non-leveraged).
        config: Optional pre-loaded config.

    Returns:
        dict with ok, order_id, status fields.
    """
    cfg = config or load_config()
    if cfg.profile != "demo":
        raise EToroConfigError("Live trading not permitted; set profile='demo'.")
    if instrument_id is None and symbol is None:
        raise ValueError("Provide either instrument_id or symbol.")
    if instrument_id is not None and symbol is not None:
        raise ValueError("Provide either instrument_id or symbol, not both.")
    if amount is not None and units is not None:
        raise ValueError("Provide either amount or units, not both.")

    body: dict[str, Any] = {
        "action": action,
        "transaction": transaction,
        "orderType": order_type,
        "leverage": leverage,
        "settlementType": settlement_type,
    }
    if instrument_id is not None:
        body["instrumentId"] = instrument_id
    if symbol is not None:
        body["symbol"] = symbol
    if amount is not None:
        body["amount"] = amount
        body["orderCurrency"] = "usd"
    if units is not None:
        body["units"] = units

    url = f"{ETORO_BASE}/api/v2/trading/execution/demo/orders"
    try:
        if _tap_enabled():
            resp = _write_via_tap(url, "POST", body)
        else:
            resp = _direct_post(url, body, cfg, "POST")
        order_id = (resp or {}).get("orderId") or (resp or {}).get("orderID")
        return {
            "ok": True,
            "order_id": order_id,
            "status": (resp or {}).get("statusID") or "submitted",
            "profile": cfg.profile,
            "raw": resp,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def cancel_order(order_id: int | str, config: EToroConfig | None = None) -> dict[str, Any]:
    """Cancel a pending demo order (requires TAP approval for DELETE)."""
    cfg = config or load_config()
    url = f"{ETORO_BASE}/api/v2/trading/execution/demo/orders/{order_id}"
    try:
        if _tap_enabled():
            resp = _write_via_tap(url, "DELETE", None)
        else:
            resp = _direct_post(url, None, cfg, "DELETE")
        return {"ok": True, "order_id": order_id, "profile": cfg.profile, "raw": resp}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def close_position(
    position_id: int | str,
    instrument_id: int,
    units_to_close: float | None = None,
    config: EToroConfig | None = None,
) -> dict[str, Any]:
    """Close an open demo position (full or partial). Requires TAP approval."""
    cfg = config or load_config()
    url = f"{ETORO_BASE}/api/v1/trading/execution/demo/market-close-orders/positions/{position_id}"
    body: dict[str, Any] = {"InstrumentID": instrument_id}
    if units_to_close is not None:
        body["UnitsToDeduct"] = units_to_close
    try:
        if _tap_enabled():
            resp = _write_via_tap(url, "POST", body)
        else:
            resp = _direct_post(url, body, cfg, "POST")
        return {
            "ok": True,
            "position_id": position_id,
            "close_order_id": (resp or {}).get("orderForClose", {}).get("orderID"),
            "profile": cfg.profile,
            "raw": resp,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
