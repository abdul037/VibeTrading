import { useEffect, useState, useCallback } from "react";
import { CheckCircle, XCircle, Clock, RefreshCw, ShieldCheck } from "lucide-react";
import { useTapPending } from "@/hooks/useTapPending";

const TAP_BASE = "http://localhost:8081";
const ADMIN_KEY = "admin-dev-key";

interface TapTransaction {
  id: string;
  created_at: string;
  target: string;
  method: string;
  body: Record<string, unknown> | null;
  status: "pending" | "forwarded" | "approved" | "denied" | "error";
  result: { ok: boolean; status_code: number; body: unknown } | null;
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
  if (target.includes("alpaca")) return "🦙 Alpaca";
  if (target.includes("etoro")) return "📈 eToro";
  return "🏦 Broker";
}

function orderSummary(body: Record<string, unknown> | null, target: string) {
  if (!body) return target;
  // eToro v2 order
  if (body.transaction || body.action) {
    const side = String(body.transaction || "").toUpperCase();
    const sym = body.symbol || `Instrument #${body.instrumentId}`;
    const amt = body.amount ? `$${body.amount}` : body.units ? `${body.units} units` : "";
    return `${side} ${sym} ${amt}`;
  }
  // Alpaca order
  if (body.side || body.symbol) {
    const side = String(body.side || "").toUpperCase();
    const sym = body.symbol;
    const qty = body.qty ? `${body.qty} shares` : body.notional ? `$${body.notional}` : "";
    return `${side} ${sym} ${qty}`;
  }
  return target.split("/").slice(-2).join("/");
}

export function Approvals() {
  const [transactions, setTransactions] = useState<TapTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actioning, setActioning] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "pending" | "done">("pending");
  const { connected } = useTapPending();

  const fetchTransactions = useCallback(async () => {
    try {
      const resp = await fetch(`${TAP_BASE}/admin/transactions?admin_key=${ADMIN_KEY}`);
      if (!resp.ok) throw new Error(`TAP returned ${resp.status}`);
      const data = await resp.json();
      // data is a dict keyed by txn_id
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

  const approve = async (id: string) => {
    setActioning(id);
    try {
      await fetch(`${TAP_BASE}/admin/approve/${id}?admin_key=${ADMIN_KEY}`, { method: "POST" });
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
            <p className="text-sm text-muted-foreground">Review and approve pending broker orders</p>
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

      {/* Filter tabs */}
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

      {/* Error */}
      {error && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 text-sm text-red-700 dark:text-red-300">
          ⚠️ Could not connect to TAP mock at {TAP_BASE}. Make sure it's running.
          <br /><code className="text-xs opacity-70">{error}</code>
        </div>
      )}

      {/* Transaction list */}
      {loading ? (
        <div className="text-center text-muted-foreground py-12">Loading transactions…</div>
      ) : filtered.length === 0 ? (
        <div className="text-center text-muted-foreground py-12">
          {filter === "pending" ? "✅ No pending orders — you're all caught up!" : "No transactions found."}
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map(txn => (
            <div
              key={txn.id}
              className={`rounded-xl border bg-card p-4 space-y-3 transition-opacity ${actioning === txn.id ? "opacity-50" : ""}`}
            >
              {/* Top row */}
              <div className="flex items-start justify-between gap-2">
                <div className="space-y-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-sm">{orderSummary(txn.body, txn.target)}</span>
                    {statusBadge(txn.status)}
                  </div>
                  <div className="text-xs text-muted-foreground flex items-center gap-2 flex-wrap">
                    <span>{brokerLabel(txn.target)}</span>
                    <span>·</span>
                    <span>{txn.method}</span>
                    <span>·</span>
                    <span>{new Date(txn.created_at).toLocaleString()}</span>
                  </div>
                </div>
              </div>

              {/* Entry / Stop / Target levels */}
              {txn.body && (txn.body._scanner_entry || txn.body.limit_price || txn.body._scanner_stop_loss) && (
                <div className="grid grid-cols-3 gap-2">
                  <div className="rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 p-3 text-center">
                    <div className="text-[10px] text-blue-500 font-semibold uppercase tracking-wide mb-0.5">Entry</div>
                    <div className="text-sm font-bold text-blue-700 dark:text-blue-300">
                      ${txn.body._scanner_entry ?? txn.body.limit_price ?? "Market"}
                    </div>
                  </div>
                  <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-3 text-center">
                    <div className="text-[10px] text-red-500 font-semibold uppercase tracking-wide mb-0.5">Stop Loss</div>
                    <div className="text-sm font-bold text-red-700 dark:text-red-300">
                      {txn.body._scanner_stop_loss
                        ? `$${txn.body._scanner_stop_loss}`
                        : txn.body.stop_loss
                          ? `$${(txn.body.stop_loss as Record<string,unknown>).stop_price}`
                          : "—"}
                    </div>
                  </div>
                  <div className="rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 p-3 text-center">
                    <div className="text-[10px] text-green-600 font-semibold uppercase tracking-wide mb-0.5">Take Profit</div>
                    <div className="text-sm font-bold text-green-700 dark:text-green-300">
                      {txn.body._scanner_take_profit
                        ? `$${txn.body._scanner_take_profit}`
                        : txn.body.take_profit
                          ? `$${(txn.body.take_profit as Record<string,unknown>).limit_price}`
                          : "—"}
                    </div>
                  </div>
                </div>
              )}

              {/* R/R ratio + rationale */}
              {txn.body && (txn.body._scanner_rationale || txn.body._scanner_rr_ratio) && (
                <div className="rounded-lg bg-muted/40 border border-border p-3 space-y-1">
                  {txn.body._scanner_rr_ratio && (
                    <div className="flex items-center gap-2 text-xs">
                      <span className="text-muted-foreground font-medium">R/R Ratio:</span>
                      <span className={`font-bold ${Number(txn.body._scanner_rr_ratio) >= 2 ? "text-green-600" : "text-yellow-600"}`}>
                        1 : {txn.body._scanner_rr_ratio}
                      </span>
                      <span className="text-muted-foreground">{Number(txn.body._scanner_rr_ratio) >= 2 ? "✅ Good" : "⚠️ Marginal"}</span>
                    </div>
                  )}
                  {txn.body._scanner_rationale && (
                    <div className="text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">Rationale: </span>
                      {String(txn.body._scanner_rationale)}
                    </div>
                  )}
                  {txn.body._scanner_confidence && (
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

              {/* Result (for done txns) */}
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
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={() => approve(txn.id)}
                    disabled={actioning === txn.id}
                    className="flex items-center gap-1.5 px-4 py-1.5 text-sm font-medium rounded-lg bg-green-600 hover:bg-green-700 text-white transition-colors disabled:opacity-50"
                  >
                    <CheckCircle size={14} /> Approve
                  </button>
                  <button
                    onClick={() => deny(txn.id)}
                    disabled={actioning === txn.id}
                    className="flex items-center gap-1.5 px-4 py-1.5 text-sm font-medium rounded-lg border border-red-300 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-50"
                  >
                    <XCircle size={14} /> Deny
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
