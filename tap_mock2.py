#!/usr/bin/env python3
"""Simple local TAP mock for development/testing.

Features:
- POST /forward: agent forwards requests (Authorization: Bearer <AGENT_KEY>)
  - GET requests are auto-approved and proxied to the target
  - POST/DELETE/etc are queued as pending approvals and must be approved
    via the admin UI at /admin
- POST /credentials: create a named multi-secret credential (name,key_id,secret_key,allowed_hosts)
- Admin UI: GET /admin lists pending requests; approve/deny via buttons

Usage:
- Run: TAP_MOCK_AGENT_KEY=agent-dev-key TAP_MOCK_ADMIN_KEY=admin-dev-key .venv-py311/bin/python tap_mock.py
- TAP_PROXY_URL for agent/.env: http://localhost:8080/forward
- TAP_AGENT_KEY: agent-dev-key

Note: This is a local development mock only. Do NOT use in production.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, abort, redirect, url_for
import requests
from pathlib import Path
from typing import Any, Dict

APP = Flask(__name__)

STORAGE_DIR = Path.home() / ".tap_mock"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
CRED_PATH = STORAGE_DIR / "credentials.json"
PENDING_PATH = STORAGE_DIR / "pending.json"

# Config via env
AGENT_KEY = os.environ.get("TAP_MOCK_AGENT_KEY", "agent-dev-key")
ADMIN_KEY = os.environ.get("TAP_MOCK_ADMIN_KEY", "admin-dev-key")
PORT = int(os.environ.get("TAP_MOCK_PORT", "8080"))

# Helpers for persistent simple storage

def _load(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, data: Any):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# Initialize stores
if not CRED_PATH.exists():
    _save(CRED_PATH, {})
if not PENDING_PATH.exists():
    _save(PENDING_PATH, {})


def _get_creds() -> Dict[str, Dict[str, Any]]:
    return _load(CRED_PATH, {})


def _save_creds(creds: Dict[str, Dict[str, Any]]):
    _save(CRED_PATH, creds)


def _get_pending() -> Dict[str, Dict[str, Any]]:
    return _load(PENDING_PATH, {})


def _save_pending(pending: Dict[str, Dict[str, Any]]):
    _save(PENDING_PATH, pending)


def _replace_credential_placeholders(headers: Dict[str, str]) -> Dict[str, str]:
    """Replace <CREDENTIAL:name.key_id> and <CREDENTIAL:name.secret_key> placeholders."""
    creds = _get_creds()
    out = dict(headers or {})
    for k, v in list(out.items()):
        if isinstance(v, str) and "<CREDENTIAL:" in v:
            token = v.strip()
            # token like <CREDENTIAL:alpaca.key_id>
            if token.startswith("<CREDENTIAL:") and token.endswith(">"):
                inner = token[len("<CREDENTIAL:") : -1]
                if "." in inner:
                    name, field = inner.split(".", 1)
                    c = creds.get(name)
                    if c and field in c:
                        out[k] = c[field]
    return out


@APP.route("/credentials", methods=["POST"])
def create_credential():
    """Create a named multi-secret credential. Protected by ADMIN_KEY via X-Admin-Key header."""
    admin = request.headers.get("X-Admin-Key")
    if admin != ADMIN_KEY:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    payload = request.get_json() or {}
    name = payload.get("name")
    key_id = payload.get("key_id")
    secret_key = payload.get("secret_key")
    allowed_hosts = payload.get("allowed_hosts", [])
    if not name or not key_id or not secret_key:
        return jsonify({"ok": False, "error": "name,key_id,secret_key required"}), 400
    creds = _get_creds()
    creds[name] = {"key_id": key_id, "secret_key": secret_key, "allowed_hosts": allowed_hosts}
    _save_creds(creds)
    return jsonify({"ok": True, "credential": {"name": name}})


@APP.route("/forward", methods=["POST"])
def forward():
    """Agent forwards a request. Accepts two invocation styles:

    1. JSON wrapper (development): {target, method, headers, body}
    2. Header-driven (TAP proxy canonical): X-TAP-Key, X-TAP-Target, X-TAP-Method
       and the raw request body. Both are supported for compatibility with the
       repository's tap_forward implementation.
    """
    # Authorization: accept either Bearer <AGENT_KEY> (dev clients) or
    # X-TAP-Key: <AGENT_KEY> (tap_forward client).
    auth = request.headers.get("Authorization", "")
    tap_key = request.headers.get("X-TAP-Key", "")
    if (auth.startswith("Bearer ") and auth.split("Bearer ",1)[1].strip() == AGENT_KEY) or (
        tap_key and tap_key == AGENT_KEY
    ):
        pass
    else:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    # Try JSON wrapper first
    payload = request.get_json(silent=True)
    target = None
    method = "GET"
    headers = {}
    body = None

    if isinstance(payload, dict) and payload.get("target"):
        target = payload.get("target")
        method = (payload.get("method") or "GET").upper()
        headers = payload.get("headers") or {}
        body = payload.get("body")
    else:
        # Header-driven invocation (tap_forward style)
        target = request.headers.get("X-TAP-Target")
        method = (request.headers.get("X-TAP-Method") or "GET").upper()
        # Build credential headers from all incoming headers except control ones
        exclude = {"X-TAP-Key", "X-TAP-Target", "X-TAP-Method", "Content-Type", "Content-Length", "Host", "Authorization"}
        for k, v in request.headers.items():
            if k not in exclude:
                headers[k] = v
        # Body: raw data (try to parse JSON)
        raw = request.get_data(as_text=True)
        if raw:
            try:
                body = json.loads(raw)
            except Exception:
                body = raw

    if not target:
        return jsonify({"ok": False, "error": "target required"}), 400

    # Replace credential placeholders in headers
    headers = _replace_credential_placeholders(headers)

    # Handle GET immediately
    if method == "GET":
        try:
            resp = requests.get(target, headers=headers, timeout=10)
            try:
                body_resp = resp.json()
            except Exception:
                body_resp = resp.text
            return jsonify({"ok": True, "body": body_resp, "status_code": resp.status_code}), 200
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    # Non-GET: queue for approval
    pending = _get_pending()
    pid = uuid.uuid4().hex
    pending[pid] = {
        "id": pid,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "target": target,
        "method": method,
        "headers": headers,
        "body": body,
        "status": "pending",
        "result": None,
    }
    _save_pending(pending)
    # Return 202 to indicate pending approval (tap_forward expects 202 for write path)
    return (jsonify({"ok": False, "txn_id": pid, "poll_url": f"/agent/approvals/{pid}"}), 202)
@APP.route("/admin", methods=["GET"])
def admin_ui():
    # Simple HTML UI protected by admin key in query or header
    key = request.args.get("admin_key") or request.headers.get("X-Admin-Key")
    if key != ADMIN_KEY:
        return "Unauthorized. Provide admin_key param or X-Admin-Key header.", 401
    pending = _get_pending()
    items = list(pending.values())
    html = ["<html><body><h1>TAP Mock Admin</h1>"]
    html.append(f"<p>Agent key: <code>{AGENT_KEY}</code></p>")
    if not items:
        html.append("<p>No pending requests.</p>")
    else:
        for item in items:
            html.append(f"<div style='border:1px solid #ccc;padding:8px;margin:8px;'>")
            html.append(f"<p><b>ID:</b> {item['id']}</p>")
            html.append(f"<p><b>Method:</b> {item['method']}</p>")
            html.append(f"<p><b>Target:</b> {item['target']}</p>")
            html.append(f"<p><b>Headers:</b> <pre>{json.dumps(item['headers'], indent=2)}</pre></p>")
            html.append(f"<p><b>Body:</b> <pre>{json.dumps(item['body'], indent=2) if item['body'] is not None else ''}</pre></p>")
            if item['status'] != 'pending':
                html.append(f"<p>Status: {item['status']}</p>")
            else:
                html.append(f"<form method='post' action='/admin/approve/{item['id']}?admin_key={ADMIN_KEY}' style='display:inline;'>")
                html.append("<button type='submit'>Approve</button></form>")
                html.append(f"<form method='post' action='/admin/deny/{item['id']}?admin_key={ADMIN_KEY}' style='display:inline;margin-left:8px;'>")
                html.append("<button type='submit'>Deny</button></form>")
            html.append("</div>")
    html.append("</body></html>")
    return '\n'.join(html)


@APP.route('/admin/approve/<pid>', methods=['POST'])
def admin_approve(pid):
    key = request.args.get("admin_key") or request.headers.get("X-Admin-Key")
    if key != ADMIN_KEY:
        return "Unauthorized", 401
    pending = _get_pending()
    item = pending.get(pid)
    if not item:
        return "Not found", 404
    if item['status'] != 'pending':
        return f"Already {item['status']}", 400
    try:
        # forward the original request now
        method = item['method']
        headers = item['headers'] or {}
        body = item['body']
        if method in ('POST', 'PUT', 'PATCH'):
            resp = requests.request(method, item['target'], headers=headers, json=body, timeout=20)
        else:
            resp = requests.request(method, item['target'], headers=headers, timeout=20)
        try:
            resp_body = resp.json()
        except Exception:
            resp_body = resp.text
        item['status'] = 'approved'
        item['result'] = {'ok': True, 'status_code': resp.status_code, 'body': resp_body}
        pending[pid] = item
        _save_pending(pending)
        return redirect(url_for('admin_ui', admin_key=ADMIN_KEY))
    except Exception as exc:
        item['status'] = 'error'
        item['result'] = {'ok': False, 'error': str(exc)}
        pending[pid] = item
        _save_pending(pending)
        return str(exc), 502


@APP.route('/admin/deny/<pid>', methods=['POST'])
def admin_deny(pid):
    key = request.args.get("admin_key") or request.headers.get("X-Admin-Key")
    if key != ADMIN_KEY:
        return "Unauthorized", 401
    pending = _get_pending()
    item = pending.get(pid)
    if not item:
        return "Not found", 404
    item['status'] = 'denied'
    item['result'] = {'ok': False, 'error': 'denied by approver'}
    pending[pid] = item
    _save_pending(pending)
    return redirect(url_for('admin_ui', admin_key=ADMIN_KEY))


@APP.route('/status', methods=['GET'])
def status():
    return jsonify({
        'ok': True,
        'agent_key': AGENT_KEY,
        'admin_key_present': bool(ADMIN_KEY),
        'credentials': list(_get_creds().keys()),
        'pending': len(_get_pending()),
    })


if __name__ == '__main__':
    print(f"Starting TAP mock on 0.0.0.0:{PORT}")
    print(f"AGENT_KEY={AGENT_KEY}  ADMIN_KEY={ADMIN_KEY}")
    APP.run(host='0.0.0.0', port=PORT)
