/**
 * useTapPending — polls TAP /admin/transactions every 10s.
 * Returns the count of pending transactions and fires browser
 * notifications when new ones arrive.
 */
import { useEffect, useRef, useState, useCallback } from "react";

const TAP_BASE = "http://localhost:8081";
const ADMIN_KEY = "admin-dev-key";
const POLL_INTERVAL = 10_000; // 10 seconds

export function useTapPending() {
  const [pendingCount, setPendingCount] = useState(0);
  const [connected, setConnected] = useState(false);
  const prevCountRef = useRef<number | null>(null);

  const requestNotifPermission = useCallback(async () => {
    if ("Notification" in window && Notification.permission === "default") {
      await Notification.requestPermission();
    }
  }, []);

  const fireNotification = useCallback((count: number) => {
    if (!("Notification" in window)) return;
    if (Notification.permission !== "granted") return;
    new Notification("🔔 Vibe Trading — Trade Approval Needed", {
      body: `${count} trade${count > 1 ? "s" : ""} waiting for your approval`,
      icon: "/favicon.ico",
      tag: "tap-pending", // deduplicate: only one notification at a time
      requireInteraction: true,
    });
  }, []);

  const poll = useCallback(async () => {
    try {
      const resp = await fetch(
        `${TAP_BASE}/admin/transactions?admin_key=${ADMIN_KEY}`,
        { signal: AbortSignal.timeout(8000) }
      );
      if (!resp.ok) { setConnected(false); return; }
      const data = await resp.json();
      const pending = Object.values(data as Record<string, { status: string }>)
        .filter((t) => t.status === "pending").length;
      setConnected(true);
      setPendingCount(pending);

      // Fire browser notification if pending count increased
      if (
        pending > 0 &&
        prevCountRef.current !== null &&
        pending > prevCountRef.current
      ) {
        fireNotification(pending);
      }
      prevCountRef.current = pending;
    } catch {
      setConnected(false);
    }
  }, [fireNotification]);

  useEffect(() => {
    // Ask for notification permission on mount
    requestNotifPermission();
    // Poll immediately then on interval
    poll();
    const id = setInterval(poll, POLL_INTERVAL);
    return () => clearInterval(id);
  }, [poll, requestNotifPermission]);

  return { pendingCount, connected };
}
