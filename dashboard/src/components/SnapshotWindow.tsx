"use client";
import { useEffect, useState, useTransition, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { snapshotRemainingMs } from "@/lib/workspace";

/** Retry delays after an expiry when the server has not produced a newer snapshot yet. */
export const RETRY_MS = [3000, 10000, 30000, 60000];

/**
 * Background snapshots expire after ~2 minutes and the worker rebuilds them
 * every minute, so on expiry the page silently re-reads the server instead of
 * asking. Client state survives router.refresh(); hidden tabs reload when they
 * become visible again.
 */
export function SnapshotWindow({ expiresAt, children }: { expiresAt: string | null; children: ReactNode }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [attempt, setAttempt] = useState(0);
  const [stale, setStale] = useState(false);
  useEffect(() => { setAttempt(0); setStale(false); }, [expiresAt]);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const reload = () => {
      if (document.visibilityState === "hidden") return;
      setStale(true);
      startTransition(() => router.refresh());
      // Same expiresAt after the refresh means no newer snapshot yet: back off and try again.
      timer = setTimeout(() => setAttempt(a => a + 1), RETRY_MS[Math.min(attempt, RETRY_MS.length - 1)]);
    };
    const schedule = () => {
      clearTimeout(timer);
      const remaining = snapshotRemainingMs(expiresAt, Date.now());
      timer = setTimeout(reload, attempt ? 0 : remaining + 250);
    };
    schedule();
    // Suspended tabs may delay timers, so recheck when returning to the page.
    const onVisible = () => { if (document.visibilityState === "visible") schedule(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { clearTimeout(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [expiresAt, attempt, router]);
  return <>
    {(stale || pending) && <p role="status" className="pointer-events-none fixed right-4 top-3 z-50 rounded-full border border-slate-700 bg-slate-900/90 px-3 py-1 text-[11px] text-slate-300 shadow">Updating…</p>}
    {children}
  </>;
}

/** Retries the server render while a snapshot is still being built, instead of a manual check button. */
export function SnapshotRetry({ everyMs = 15000 }: { everyMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") router.refresh(); }, everyMs);
    return () => clearInterval(timer);
  }, [router, everyMs]);
  return <p className="mt-3 text-xs text-slate-500">Checking again automatically…</p>;
}
