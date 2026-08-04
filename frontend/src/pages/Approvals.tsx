import { useEffect, useState, useCallback } from "react";
import { CheckCircle, XCircle, Clock, RefreshCw, ShieldCheck, Edit3, Trash2 } from "lucide-react";
import { useTapPending } from "@/hooks/useTapPending";

const TAP_BASE = "http://localhost:8081";
const ADMIN_KEY = "admin-dev-key";

const TIMEFRAME_COLORS: Record<string, string> = {
  "1min":      "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300",
  "5min":      "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300",
  "30min":     "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300",
  "2hr":       "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  "5hr":       "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300",
  "multi-day": "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
};

const TIMEFRAME_OPTIONS = ["1min", "5min", "30min", "2hr", "5hr", "multi-day"];

interface TapTransaction {
  id: string;
  created_at: string;
  target: string;
  method: string;
  body: Record<string, unknown> | null;
  status: "pending" | "forwarded" | "approved" | "denied" | "error";
  result: { ok: boolean; status_code: number; body: unknown } | null;
}

// Per-card editable state
interface EditState {
  stopLoss: string;
  takeProfit: string;
  timeframe: string;
  editing: boolean;
}

function statusBadge(status: string) {
  switch (status) {
    case "pending":
      return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300"><Clock size={11} /> Pending</span>;
    case "forwarded":
    case "approved":
      return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300"><CheckCircle size={11} /> Approved</span>;
    case "denied":
      return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300"><XCircle size={11} /> Denied</span>;
    default:
      return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">{status}</span>;
  }
}

function brokerLabel(target: string) {
  if (target.includes("alpaca")) return "🦙 Alpaca Paper";
  if (target.includes("etoro")) return "📈 eToro Demo";
  return "🏦 Broker";
}

function timeframeBadge(tf: string) {
  const cls = TIMEFRAME_COLORS[tf] ?? "bg-gray-100 text-gray-600";
  const labels: Record<string, string> = {
    "1min": "⚡ 1 min scalp",
    "5min": "⚡ 5 min scalp",
    "30min": "📊 30 min swing",
    "2hr": "🕐 2 hr swing",
    "5hr": "🕔 5 hr intraday",
    "multi-day": "📅 Multi-day hold",
  };
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${cls}`}>
      {labels[tf] ?? tf}
    </span>
  );
}

function orderSummary(body: Record<string, unknown> | null, target: string) {
  if (!body) return target;
  if (body.transaction || body.action) {
    const side = String(body.transaction || "BUY").toUpperCase();
    const sym = body.symbol || `Instrument #${body.instrumentId}`;
    const amt = body.amount ? `$${body.amount}` : body.units ? `${body.units} units` : "";
    return `${side} ${sym} ${amt}`;
  }
  if (body.side || body.symbol) {
    const side = String(body.side || "BUY").toUpperCase();
    const sym = body.symbol;
    const qty = body.qty ? `${body.qty} shares` : body.notional ? `$${body.notional}` : "";
    return `${side} ${sym} ${qty}`;
  }
  return target.split("/").slice(-2).join("/");
}

function getField(body: Record<string, unknown> | null, ...keys: string[]): string {
  if (!body) return "";
  for (const k of keys) {
    if (body[k] !== undefined && body[k] !== null) return String(body[k]);
  }
  return "";
}

export function Approvals() {
  const [transactions, setTransactions] = useState<TapTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actioning, setActioning] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "pending" | "done">("pending");
  const [edits, setEdits] = useState<Record<string, EditState>>({});
  const { connected } = useTapPending();

  const fetchTransactions = useCallback(async () => {
    try {
      const resp = await fetch(`${TAP_BASE}/admin/transactions?admin_key=${ADMIN_KEY}`);
      if (!resp.ok) throw new Error(`TAP returned ${resp.status}`);
      const data = await resp.json();
      const list = Object.values(data) as TapTransaction[];
      list.sort((a, b) => b.created_at.localeCompare(a.created_at));
      setTransactions(list);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTransactions();
    const interval = setInterval(fetchTransactions, 5000);
    return () => clearInterval(interval);
  }, [fetchTransactions]);

  // Initialise edit state for a txn if not yet set
  const getEdit = (txn: TapTransaction): EditState => {
    if (edits[txn.id]) return edits[txn.id];
    const sl = getField(txn.body, "_scanner_stop_loss") ||
      (txn.body?.stop_loss ? String((txn.body.stop_loss as Record<string,unknown>).stop_price ?? "") : "");
    const tp = getField(txn.body, "_scanner_take_profit") ||
      (txn.body?.take_profit ? String((txn.body.take_profit as Record<string,unknown>).limit_price ?? "") : "");
    const tf = getField(txn.body, "_scanner_timeframe") || "multi-day";
    return { stopLoss: sl, takeProfit: tp, timeframe: tf, editing: false };
  };

  const setEdit = (id: string, patch: Partial<EditState>) =>
    setEdits(prev => ({ ...prev, [id]: { ...getEdit({ id } as TapTransaction), ...prev[id], ...patch } }));

  const approve = async (txn: TapTransaction) => {
    setActioning(txn.id);
    const edit = getEdit(txn);
    // Patch the body metadata before approving (store amended values)
    const amendedMeta = {
      _amended_stop_loss: edit.stopLoss,
      _amended_take_profit: edit.takeProfit,
      _amended_timeframe: edit.timeframe,
    };
    try {
      // POST approve with amended values as query params for display
      const params = new URLSearchParams({
        admin_key: ADMIN_KEY,
        stop_loss: edit.stopLoss,
        take_profit: edit.takeProfit,
        timeframe: edit.timeframe,
      });
      await fetch(`${TAP_BASE}/admin/approve/${txn.id}?${params}`, { method: "POST" });
      console.log("Approved with amendments", amendedMeta);
      await fetchTransactions();
    } finally {
      setActioning(null);
    }
  };

  const deny = async (id: string) => {
    setActioning(id);
    try {
      await fetch(`${TAP_BASE}/admin/deny/${id}?admin_key=${ADMIN_KEY}`, { method: "POST" });
      await fetchTransactions();
    } finally {
      setActioning(null);
    }
  };

  const clearDone = async () => {
    await fetch(`${TAP_BASE}/admin/clear?admin_key=${ADMIN_KEY}&scope=done`, { method: "POST" });
    await fetchTransactions();
  };

  const clearAll = async () => {
    await fetch(`${TAP_BASE}/admin/clear?admin_key=${ADMIN_KEY}&scope=all`, { method: "POST" });
    await fetchTransactions();
  };

  const denyAllPending = async () => {
    await fetch(`${TAP_BASE}/admin/deny/all?admin_key=${ADMIN_KEY}`, { method: "POST" });
    await fetchTransactions();
  };

  const pendingCount = transactions.filter(t => t.status === "pending").length;
  const filtered = transactions.filter(t => {
    if (filter === "pending") return t.status === "pending";
    if (filter === "done") return t.status !== "pending";
    return true;
  });

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ShieldCheck className="text-blue-500" size={26} />
          <div>
            <h1 className="text-xl font-semibold">Trade Approvals</h1>
            <p className="text-sm text-muted-foreground">Review, edit stop/target, then approve pending orders</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`flex items-center gap-1 text-xs ${connected ? "text-green-500" : "text-red-400"}`}>
            <span className={`inline-block h-2 w-2 rounded-full ${connected ? "bg-green-500 animate-pulse" : "bg-red-400"}`} />
            {connected ? "TAP live" : "TAP offline"}
          </span>
          <button
            onClick={fetchTransactions}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-border hover:bg-muted transition-colors"
          >
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Pending", count: transactions.filter(t => t.status === "pending").length, color: "text-yellow-600" },
          { label: "Approved", count: transactions.filter(t => ["forwarded","approved"].includes(t.status)).length, color: "text-green-600" },
          { label: "Denied", count: transactions.filter(t => t.status === "denied").length, color: "text-red-500" },
        ].map(({ label, count, color }) => (
          <div key={label} className="rounded-xl border border-border bg-card p-4 text-center">
            <div className={`text-2xl font-bold ${color}`}>{count}</div>
            <div className="text-xs text-muted-foreground mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      {/* Filter tabs + bulk actions */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex gap-2 text-sm">
          {(["pending", "all", "done"] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded-full border transition-colors capitalize ${filter === f ? "bg-primary text-primary-foreground border-primary" : "border-border hover:bg-muted"}`}
            >
              {f === "pending" && pendingCount > 0 ? `Pending (${pendingCount})` : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <div className="flex gap-2 text-xs">
          {pendingCount > 0 && (
            <button
              onClick={denyAllPending}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-red-300 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
            >
              <XCircle size={12} /> Deny All Pending
            </button>
          )}
          <button
            onClick={clearDone}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-border hover:bg-muted transition-colors text-muted-foreground"
          >
            <Trash2 size={12} /> Clear Done
          </button>
          <button
            onClick={clearAll}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-border hover:bg-muted transition-colors text-muted-foreground"
          >
            <Trash2 size={12} /> Clear All
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 text-sm text-red-700 dark:text-red-300">
          ⚠️ Could not connect to TAP mock at {TAP_BASE}. Make sure it's running.
          <br /><code className="text-xs opacity-70">{error}</code>
        </div>
      )}

      {loading ? (
        <div className="text-center text-muted-foreground py-12">Loading transactions…</div>
      ) : filtered.length === 0 ? (
        <div className="text-center text-muted-foreground py-12">
          {filter === "pending" ? "✅ No pending orders — you're all caught up!" : "No transactions found."}
        </div>
      ) : (
        <div className="space-y-4">
          {filtered.map(txn => {
            const edit = { ...getEdit(txn), ...edits[txn.id] };
            const isEditing = edit.editing;
            const entry = getField(txn.body, "_scanner_entry", "limit_price");
            const hasLevels = !!(entry || edit.stopLoss || edit.takeProfit);
            const rrNum = txn.body?._scanner_rr_ratio ? Number(txn.body._scanner_rr_ratio) : null;

            return (
              <div
                key={txn.id}
                className={`rounded-xl border bg-card p-4 space-y-4 transition-opacity ${actioning === txn.id ? "opacity-50" : ""} ${txn.status === "pending" ? "border-yellow-300 dark:border-yellow-700" : "border-border"}`}
              >
                {/* Top row: symbol + badges */}
                <div className="flex items-start justify-between gap-2 flex-wrap">
                  <div className="space-y-1.5 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-base">{orderSummary(txn.body, txn.target)}</span>
                      {statusBadge(txn.status)}
                      {timeframeBadge(edit.timeframe)}
                    </div>
                    <div className="text-xs text-muted-foreground flex items-center gap-2 flex-wrap">
                      <span>{brokerLabel(txn.target)}</span>
                      <span>·</span>
                      <span>{new Date(txn.created_at).toLocaleString()}</span>
                    </div>
                  </div>
                  {txn.status === "pending" && (
                    <button
                      onClick={() => setEdit(txn.id, { editing: !isEditing })}
                      className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-border hover:bg-muted transition-colors text-muted-foreground"
                    >
                      <Edit3 size={11} /> {isEditing ? "Done" : "Edit levels"}
                    </button>
                  )}
                </div>

                {/* Entry / Stop / Target — view or edit mode */}
                {hasLevels && (
                  <div className="space-y-2">
                    <div className="grid grid-cols-3 gap-2">
                      {/* Entry (read-only) */}
                      <div className="rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 p-3 text-center">
                        <div className="text-[10px] text-blue-500 font-semibold uppercase tracking-wide mb-0.5">Entry</div>
                        <div className="text-sm font-bold text-blue-700 dark:text-blue-300">
                          {entry ? `$${Number(entry).toFixed(2)}` : "Market"}
                        </div>
                      </div>

                      {/* Stop Loss — editable */}
                      <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-3 text-center">
                        <div className="text-[10px] text-red-500 font-semibold uppercase tracking-wide mb-0.5">Stop Loss</div>
                        {isEditing ? (
                          <input
                            type="number"
                            step="0.01"
                            value={edit.stopLoss}
                            onChange={e => setEdit(txn.id, { stopLoss: e.target.value })}
                            className="w-full text-center text-sm font-bold text-red-700 dark:text-red-300 bg-transparent border-b border-red-300 focus:outline-none focus:border-red-500"
                          />
                        ) : (
                          <div className="text-sm font-bold text-red-700 dark:text-red-300">
                            {edit.stopLoss ? `$${Number(edit.stopLoss).toFixed(2)}` : "—"}
                          </div>
                        )}
                      </div>

                      {/* Take Profit — editable */}
                      <div className="rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 p-3 text-center">
                        <div className="text-[10px] text-green-600 font-semibold uppercase tracking-wide mb-0.5">Take Profit</div>
                        {isEditing ? (
                          <input
                            type="number"
                            step="0.01"
                            value={edit.takeProfit}
                            onChange={e => setEdit(txn.id, { takeProfit: e.target.value })}
                            className="w-full text-center text-sm font-bold text-green-700 dark:text-green-300 bg-transparent border-b border-green-300 focus:outline-none focus:border-green-500"
                          />
                        ) : (
                          <div className="text-sm font-bold text-green-700 dark:text-green-300">
                            {edit.takeProfit ? `$${Number(edit.takeProfit).toFixed(2)}` : "—"}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Timeframe selector in edit mode */}
                    {isEditing && (
                      <div className="flex items-center gap-2 flex-wrap pt-1">
                        <span className="text-xs text-muted-foreground font-medium">Timeframe:</span>
                        {TIMEFRAME_OPTIONS.map(tf => (
                          <button
                            key={tf}
                            onClick={() => setEdit(txn.id, { timeframe: tf })}
                            className={`px-2.5 py-0.5 rounded-full text-xs font-medium border transition-colors ${
                              edit.timeframe === tf
                                ? "bg-primary text-primary-foreground border-primary"
                                : "border-border hover:bg-muted"
                            }`}
                          >
                            {tf}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* R/R + rationale */}
                {txn.body && (txn.body._scanner_rationale || rrNum !== null) && (
                  <div className="rounded-lg bg-muted/40 border border-border p-3 space-y-1">
                    {rrNum !== null && (
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-muted-foreground font-medium">R/R Ratio:</span>
                        <span className={`font-bold ${rrNum >= 2 ? "text-green-600" : "text-yellow-600"}`}>
                          1 : {rrNum}
                        </span>
                        <span className="text-muted-foreground">{rrNum >= 2 ? "✅ Good" : "⚠️ Marginal"}</span>
                      </div>
                    )}
                    {txn.body._scanner_rationale != null && (
                      <div className="text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">Signal: </span>
                        {String(txn.body._scanner_rationale)}
                      </div>
                    )}
                    {txn.body._scanner_confidence != null && (
                      <div className="text-xs">
                        <span className="text-muted-foreground font-medium">Confidence: </span>
                        <span className={`font-semibold capitalize ${
                          txn.body._scanner_confidence === "high" ? "text-green-600" :
                          txn.body._scanner_confidence === "medium" ? "text-yellow-600" : "text-gray-500"
                        }`}>{String(txn.body._scanner_confidence)}</span>
                      </div>
                    )}
                  </div>
                )}

                {/* Result */}
                {txn.result && txn.status !== "pending" && (
                  <div className="text-xs text-muted-foreground">
                    {txn.result.ok
                      ? <span className="text-green-600">✅ Executed · HTTP {txn.result.status_code}</span>
                      : <span className="text-red-500">❌ Failed · HTTP {txn.result.status_code}</span>
                    }
                  </div>
                )}

                {/* Action buttons */}
                {txn.status === "pending" && (
                  <div className="flex gap-2 pt-1 border-t border-border">
                    <button
                      onClick={() => approve(txn)}
                      disabled={actioning === txn.id}
                      className="flex items-center gap-1.5 px-5 py-2 text-sm font-semibold rounded-lg bg-green-600 hover:bg-green-700 text-white transition-colors disabled:opacity-50"
                    >
                      <CheckCircle size={15} /> Approve & Execute
                    </button>
                    <button
                      onClick={() => deny(txn.id)}
                      disabled={actioning === txn.id}
                      className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg border border-red-300 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-50"
                    >
                      <XCircle size={14} /> Deny
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
