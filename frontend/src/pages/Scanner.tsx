import { useState, useEffect, useCallback } from "react";
import { Play, RefreshCw, Clock, CheckCircle, XCircle, BarChart2, Zap, TrendingUp, AlertCircle } from "lucide-react";

const API_BASE = "http://localhost:8000";

const TIMEFRAME_COLORS: Record<string, string> = {
  "1min":      "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300",
  "5min":      "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300",
  "30min":     "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300",
  "2hr":       "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  "5hr":       "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300",
  "multi-day": "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
};

interface ScannerStatus {
  active_jobs: number;
  last_scan: {
    file?: string;
    scan_date?: string;
    scanned?: number;
    universe_size?: number;
    proposals_count?: number;
    top_symbols?: string[];
  };
}

interface Proposal {
  symbol: string;
  action: string;
  amount_usd: number;
  entry?: number;
  stop_loss?: number;
  take_profit?: number;
  rr_ratio?: number;
  timeframe?: string;
  rationale?: string;
  confidence?: string;
  brokers?: string[];
}

interface ScanHistory {
  file: string;
  scan_date: string;
  scanned: number;
  universe_size: number;
  proposals_count: number;
  proposals: Proposal[];
  top_candidates: Array<{ symbol: string; score: number; price: number; rsi?: number; signals: string[] }>;
}

interface Job {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  started_at: string;
  finished_at?: string;
  error?: string;
  proposals_count?: number;
  scanned?: number;
  tap_txn_ids?: string[];
}

function confidenceDot(c?: string) {
  if (c === "high") return <span className="h-2 w-2 rounded-full bg-green-500 inline-block" />;
  if (c === "medium") return <span className="h-2 w-2 rounded-full bg-yellow-500 inline-block" />;
  return <span className="h-2 w-2 rounded-full bg-gray-400 inline-block" />;
}

function timeframePill(tf?: string) {
  if (!tf) return null;
  const cls = TIMEFRAME_COLORS[tf] ?? "bg-gray-100 text-gray-600";
  return <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${cls}`}>{tf}</span>;
}

export function Scanner() {
  const [status, setStatus] = useState<ScannerStatus | null>(null);
  const [history, setHistory] = useState<ScanHistory[]>([]);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [queueToTap, setQueueToTap] = useState(true);
  const [loading, setLoading] = useState(false);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [selectedScan, setSelectedScan] = useState<ScanHistory | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/scanner/status`);
      if (!r.ok) throw new Error();
      setStatus(await r.json());
      setApiOnline(true);
    } catch {
      setApiOnline(false);
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/scanner/proposals`);
      if (!r.ok) return;
      const data: ScanHistory[] = await r.json();
      setHistory(data);
      if (data.length > 0 && !selectedScan) setSelectedScan(data[0]);
    } catch {}
  }, [selectedScan]);

  const fetchJobs = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/scanner/jobs`);
      if (!r.ok) return;
      const data: Job[] = await r.json();
      const running = data.find(j => j.status === "running" || j.status === "queued");
      setActiveJob(running ?? null);
    } catch {}
  }, []);

  useEffect(() => {
    fetchStatus();
    fetchHistory();
    fetchJobs();
    const interval = setInterval(() => {
      fetchStatus();
      fetchJobs();
      if (activeJob) fetchHistory();
    }, 4000);
    return () => clearInterval(interval);
  }, [fetchStatus, fetchHistory, fetchJobs, activeJob]);

  // Poll active job faster
  useEffect(() => {
    if (!activeJob) return;
    const poll = setInterval(async () => {
      try {
        const r = await fetch(`${API_BASE}/api/scanner/jobs/${activeJob.job_id}`);
        const job: Job = await r.json();
        setActiveJob(job.status === "running" || job.status === "queued" ? job : null);
        if (job.status === "done" || job.status === "error") {
          fetchHistory();
          fetchStatus();
        }
      } catch {}
    }, 2000);
    return () => clearInterval(poll);
  }, [activeJob, fetchHistory, fetchStatus]);

  const runScan = async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API_BASE}/api/scanner/run?queue=${queueToTap}`, { method: "POST" });
      const job: Job = await r.json();
      setActiveJob(job);
    } catch {
    } finally {
      setLoading(false);
    }
  };

  const isRunning = !!(activeJob && (activeJob.status === "running" || activeJob.status === "queued"));

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <BarChart2 className="text-blue-500" size={26} />
          <div>
            <h1 className="text-xl font-semibold">Market Scanner</h1>
            <p className="text-sm text-muted-foreground">
              S&P 500 daily scan · RSI · ATR · momentum · entry/exit levels
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`flex items-center gap-1 text-xs ${apiOnline ? "text-green-500" : "text-red-400"}`}>
            <span className={`inline-block h-2 w-2 rounded-full ${apiOnline ? "bg-green-500 animate-pulse" : "bg-red-400"}`} />
            {apiOnline ? "API online" : "API offline"}
          </span>
          <button onClick={() => { fetchStatus(); fetchHistory(); fetchJobs(); }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-border hover:bg-muted transition-colors">
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {/* API offline warning */}
      {apiOnline === false && (
        <div className="rounded-lg bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-700 p-4 text-sm text-yellow-800 dark:text-yellow-300 flex items-start gap-2">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <div>
            <strong>Backend API not running.</strong> Start it with:
            <code className="block mt-1 text-xs bg-black/10 rounded px-2 py-1">
              cd agent && ../.venv-py311/bin/uvicorn api_server:app --port 8000
            </code>
          </div>
        </div>
      )}

      {/* Stats bar */}
      {status && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Universe", value: status.last_scan.universe_size ?? "—", icon: <BarChart2 size={14} />, color: "text-blue-600" },
            { label: "Last Scanned", value: status.last_scan.scanned ?? "—", icon: <TrendingUp size={14} />, color: "text-green-600" },
            { label: "Proposals", value: status.last_scan.proposals_count ?? "—", icon: <Zap size={14} />, color: "text-purple-600" },
            { label: "Active Jobs", value: status.active_jobs, icon: <Clock size={14} />, color: "text-yellow-600" },
          ].map(({ label, value, icon, color }) => (
            <div key={label} className="rounded-xl border border-border bg-card p-4 text-center">
              <div className={`flex items-center justify-center gap-1 text-2xl font-bold ${color}`}>
                {icon}{value}
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Run scanner */}
      <div className="rounded-xl border border-border bg-card p-5 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h2 className="font-semibold text-base">Run Scanner Now</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Scans ~378 S&P 500 symbols · computes RSI, ATR, momentum · generates top 3 proposals
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
              <input
                type="checkbox"
                checked={queueToTap}
                onChange={e => setQueueToTap(e.target.checked)}
                className="rounded"
              />
              Send to Approvals
            </label>
            <button
              onClick={runScan}
              disabled={loading || isRunning || apiOnline === false}
              className="flex items-center gap-2 px-5 py-2.5 text-sm font-semibold rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-50"
            >
              {isRunning ? (
                <><RefreshCw size={15} className="animate-spin" /> Scanning…</>
              ) : (
                <><Play size={15} /> Run Scan</>
              )}
            </button>
          </div>
        </div>

        {/* Active job progress */}
        {activeJob && (
          <div className={`rounded-lg p-3 text-sm border ${
            activeJob.status === "running" ? "bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-700" :
            activeJob.status === "done" ? "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-700" :
            "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-700"
          }`}>
            <div className="flex items-center gap-2">
              {activeJob.status === "running" || activeJob.status === "queued"
                ? <RefreshCw size={14} className="animate-spin text-blue-500" />
                : activeJob.status === "done"
                  ? <CheckCircle size={14} className="text-green-600" />
                  : <XCircle size={14} className="text-red-500" />
              }
              <span className="font-medium capitalize">{activeJob.status}</span>
              {activeJob.scanned && <span className="text-muted-foreground">· {activeJob.scanned} symbols scanned</span>}
              {activeJob.proposals_count != null && <span className="text-muted-foreground">· {activeJob.proposals_count} proposals</span>}
              {activeJob.tap_txn_ids && activeJob.tap_txn_ids.length > 0 && (
                <span className="text-green-700 dark:text-green-400 ml-1">
                  · {activeJob.tap_txn_ids.length} queued for approval
                </span>
              )}
            </div>
            {activeJob.error && <p className="text-red-600 text-xs mt-1">{activeJob.error}</p>}
          </div>
        )}

        {/* Schedule info */}
        <p className="text-xs text-muted-foreground border-t border-border pt-3">
          🕐 <strong>Auto-schedule:</strong> Scanner daemon fires at <strong>9:30 AM ET</strong> daily (Mon–Fri) when running.
          Start it with: <code className="bg-muted px-1 rounded text-[11px]">./scripts/start_scanner.sh</code>
        </p>
      </div>

      {/* Scan history */}
      {history.length > 0 && (
        <div className="space-y-3">
          <h2 className="font-semibold text-base">Scan History</h2>
          <div className="flex gap-2 flex-wrap">
            {history.slice(0, 10).map(h => (
              <button
                key={h.file}
                onClick={() => setSelectedScan(h)}
                className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${selectedScan?.file === h.file ? "bg-primary text-primary-foreground border-primary" : "border-border hover:bg-muted"}`}
              >
                {h.scan_date ? new Date(h.scan_date).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : h.file}
              </button>
            ))}
          </div>

          {selectedScan && (
            <div className="rounded-xl border border-border bg-card p-5 space-y-5">
              <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span>📊 {selectedScan.scanned} of {selectedScan.universe_size} symbols scanned</span>
                <span>{selectedScan.scan_date ? new Date(selectedScan.scan_date).toLocaleString() : ""}</span>
              </div>

              {/* Top candidates */}
              {selectedScan.top_candidates.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold mb-2">Top Signals</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-border text-muted-foreground">
                          <th className="text-left py-1.5 pr-4">Symbol</th>
                          <th className="text-right pr-4">Price</th>
                          <th className="text-right pr-4">RSI</th>
                          <th className="text-right pr-4">Score</th>
                          <th className="text-left">Signals</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedScan.top_candidates.map(c => (
                          <tr key={c.symbol} className="border-b border-border/50 hover:bg-muted/30">
                            <td className="py-1.5 pr-4 font-bold">{c.symbol}</td>
                            <td className="text-right pr-4">${c.price?.toFixed(2)}</td>
                            <td className={`text-right pr-4 font-semibold ${c.rsi != null && c.rsi < 30 ? "text-red-600" : c.rsi != null && c.rsi < 40 ? "text-yellow-600" : "text-muted-foreground"}`}>
                              {c.rsi?.toFixed(1) ?? "—"}
                            </td>
                            <td className="text-right pr-4 font-semibold text-blue-600">{c.score?.toFixed(1)}</td>
                            <td className="text-muted-foreground truncate max-w-[200px]">{c.signals?.join(" · ")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Proposals */}
              {selectedScan.proposals.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold mb-3">📋 Proposals ({selectedScan.proposals.length})</h3>
                  <div className="space-y-3">
                    {selectedScan.proposals.map((p, i) => (
                      <div key={i} className="rounded-lg border border-border p-4 space-y-3">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-bold text-base">BUY {p.symbol}</span>
                          <span className="text-sm text-muted-foreground">${p.amount_usd}</span>
                          {timeframePill(p.timeframe)}
                          {confidenceDot(p.confidence)}
                          <span className="text-xs text-muted-foreground capitalize">{p.confidence}</span>
                          {p.brokers?.map(b => (
                            <span key={b} className="text-xs px-1.5 py-0.5 rounded bg-muted border border-border">
                              {b === "etoro" ? "📈 eToro" : "🦙 Alpaca"}
                            </span>
                          ))}
                        </div>
                        <div className="grid grid-cols-3 gap-2 text-center text-xs">
                          <div className="rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 p-2">
                            <div className="text-[10px] text-blue-500 font-semibold uppercase mb-0.5">Entry</div>
                            <div className="font-bold text-blue-700 dark:text-blue-300">{p.entry ? `$${p.entry}` : "Market"}</div>
                          </div>
                          <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-2">
                            <div className="text-[10px] text-red-500 font-semibold uppercase mb-0.5">Stop Loss</div>
                            <div className="font-bold text-red-700 dark:text-red-300">{p.stop_loss ? `$${p.stop_loss}` : "—"}</div>
                          </div>
                          <div className="rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 p-2">
                            <div className="text-[10px] text-green-600 font-semibold uppercase mb-0.5">Take Profit</div>
                            <div className="font-bold text-green-700 dark:text-green-300">{p.take_profit ? `$${p.take_profit}` : "—"}</div>
                          </div>
                        </div>
                        {p.rr_ratio != null && (
                          <div className="text-xs text-muted-foreground">
                            R/R: <span className={`font-bold ${p.rr_ratio >= 2 ? "text-green-600" : "text-yellow-600"}`}>1:{p.rr_ratio}</span>
                            {" · "}{p.rationale}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
