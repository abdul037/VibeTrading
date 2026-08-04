"""Scanner API routes — trigger scans, check status, list proposals from the frontend UI.

Endpoints:
  GET  /api/scanner/status          — last scan metadata, daemon running state
  POST /api/scanner/run             — trigger an immediate scan (async, returns job_id)
  GET  /api/scanner/jobs/{job_id}   — poll job status
  GET  /api/scanner/proposals       — list saved proposal files (latest first)
  GET  /api/scanner/proposals/latest — return the latest scan result JSON
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

PROPOSALS_DIR = Path.home() / ".vibe-trading" / "proposals"
PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job registry  {job_id: {status, started_at, result, error}}
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def _load_alpaca_env() -> None:
    if os.environ.get("ALPACA_API_KEY"):
        return
    creds_path = Path.home() / ".vibe-trading" / "alpaca.json"
    if not creds_path.exists():
        return
    try:
        creds = json.loads(creds_path.read_text())
        os.environ["ALPACA_API_KEY"] = creds.get("api_key", "")
        os.environ["ALPACA_SECRET_KEY"] = creds.get("secret_key", "")
    except Exception:
        pass


def _run_scan_job(job_id: str, queue: bool) -> None:
    """Background thread: run the scanner and update job state."""
    _load_alpaca_env()
    with _jobs_lock:
        _jobs[job_id]["status"] = "running"

    try:
        import sys, os as _os
        # Make sure agent src is importable
        agent_dir = Path(__file__).parent.parent.parent
        if str(agent_dir) not in sys.path:
            sys.path.insert(0, str(agent_dir))

        from src.scanner.proposals import run_scan

        result = run_scan(top_n=20, max_proposals=3)

        # Save to disk
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = PROPOSALS_DIR / f"scan_{date_str}.json"
        out_path.write_text(json.dumps(result, indent=2))

        # Optionally queue in TAP
        if queue and result.get("proposals"):
            from src.scanner.scheduler import _queue_proposals_in_tap
            txn_ids = _queue_proposals_in_tap(result["proposals"])
            result["tap_txn_ids"] = txn_ids

        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = result
            _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
            _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()


def _latest_proposal_file() -> Path | None:
    files = sorted(PROPOSALS_DIR.glob("scan_*.json"), reverse=True)
    return files[0] if files else None


def register_scanner_routes(app: FastAPI) -> None:

    @app.get("/api/scanner/status")
    async def scanner_status() -> JSONResponse:
        latest = _latest_proposal_file()
        last_scan: dict[str, Any] = {}
        if latest:
            try:
                data = json.loads(latest.read_text())
                last_scan = {
                    "file": latest.name,
                    "scan_date": data.get("scan_date"),
                    "scanned": data.get("scanned", 0),
                    "universe_size": data.get("universe_size", 0),
                    "proposals_count": len(data.get("proposals", [])),
                    "top_symbols": [c["symbol"] for c in data.get("top_candidates", [])[:5]],
                }
            except Exception:
                pass

        # Active jobs
        with _jobs_lock:
            active = [j for j in _jobs.values() if j["status"] == "running"]

        return JSONResponse({
            "daemon_running": False,  # future: check PID file
            "active_jobs": len(active),
            "last_scan": last_scan,
            "proposals_dir": str(PROPOSALS_DIR),
        })

    @app.post("/api/scanner/run")
    async def scanner_run(queue: bool = True) -> JSONResponse:
        job_id = uuid.uuid4().hex[:12]
        with _jobs_lock:
            _jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "queue": queue,
                "result": None,
                "error": None,
                "finished_at": None,
            }
        t = threading.Thread(target=_run_scan_job, args=(job_id, queue), daemon=True)
        t.start()
        return JSONResponse({"job_id": job_id, "status": "queued"})

    @app.get("/api/scanner/jobs/{job_id}")
    async def scanner_job_status(job_id: str) -> JSONResponse:
        with _jobs_lock:
            job = _jobs.get(job_id)
        if not job:
            return JSONResponse({"error": "job not found"}, status_code=404)
        # Strip heavy result for polling — frontend can fetch /proposals/latest when done
        return JSONResponse({
            "job_id": job["job_id"],
            "status": job["status"],
            "started_at": job["started_at"],
            "finished_at": job.get("finished_at"),
            "error": job.get("error"),
            "proposals_count": len(job["result"].get("proposals", [])) if job.get("result") else None,
            "scanned": job["result"].get("scanned") if job.get("result") else None,
            "tap_txn_ids": job["result"].get("tap_txn_ids") if job.get("result") else None,
        })

    @app.get("/api/scanner/jobs")
    async def scanner_jobs_list() -> JSONResponse:
        with _jobs_lock:
            jobs = [
                {k: v for k, v in j.items() if k != "result"}
                for j in sorted(_jobs.values(), key=lambda x: x["started_at"], reverse=True)
            ]
        return JSONResponse(jobs)

    @app.get("/api/scanner/proposals")
    async def scanner_proposals_list() -> JSONResponse:
        files = sorted(PROPOSALS_DIR.glob("scan_*.json"), reverse=True)[:20]
        out = []
        for f in files:
            try:
                data = json.loads(f.read_text())
                out.append({
                    "file": f.name,
                    "scan_date": data.get("scan_date"),
                    "scanned": data.get("scanned", 0),
                    "universe_size": data.get("universe_size", 0),
                    "proposals_count": len(data.get("proposals", [])),
                    "proposals": data.get("proposals", []),
                    "top_candidates": data.get("top_candidates", [])[:5],
                })
            except Exception:
                pass
        return JSONResponse(out)

    @app.get("/api/scanner/proposals/latest")
    async def scanner_proposals_latest() -> JSONResponse:
        latest = _latest_proposal_file()
        if not latest:
            return JSONResponse({"error": "no scans yet"}, status_code=404)
        return JSONResponse(json.loads(latest.read_text()))
