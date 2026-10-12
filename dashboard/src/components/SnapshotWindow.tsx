"use client";
import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { snapshotRemainingMs } from "@/lib/workspace";

/** Hide expired decisions even when a browser keeps an old route mounted. */
export function SnapshotWindow({ expiresAt, children }: { expiresAt: string | null; children: ReactNode }) {
  const router = useRouter();
  const [expired, setExpired] = useState(false);
  useEffect(() => {
    const check = () => setExpired(snapshotRemainingMs(expiresAt, Date.now()) === 0);
    check();
    const timer = setTimeout(check, snapshotRemainingMs(expiresAt, Date.now()) + 10);
    // Suspended tabs may delay timers, so recheck when returning to the page.
    document.addEventListener("visibilitychange", check);
    return () => { clearTimeout(timer); document.removeEventListener("visibilitychange", check); };
  }, [expiresAt]);
  if (expired) return <div role="status" className="mt-4 rounded-lg border border-amber-800 p-4">
    <p className="text-sm text-amber-200">This snapshot has expired. Candidate decisions are hidden until a current snapshot is available.</p>
    <button onClick={() => router.refresh()} className="mt-3 min-h-11 rounded-lg border border-slate-600 px-4 text-sm">Check for an updated snapshot</button>
  </div>;
  return <>{children}</>;
}
