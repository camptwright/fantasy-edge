import { fantasyApi } from "@/lib/fantasy-api";

type Operations = { status: string; alerts: string[]; latest?: { at: string; performance: { peak_rss_bytes?: number } } };
type Odds = { configured?: boolean; quota_blocked?: boolean; quota_floor?: number; telemetry?: { remaining?: number | null; used?: number | null; observed_at?: string };
  sports?: { sport: string; reason: string; window_opens_at?: string | null }[] };
type Props = { enabled?: boolean; providers?: Record<string, { configured: boolean; daily_limit: number; reserved_today: number; unit: string; blocked_seconds: number }> };

const label = (s: string) => s.replaceAll("_", " ");
const when = (iso?: string | null) => iso ? new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/Chicago" }) : "never";

function Tile({ k, v, sub, tone = "" }: { k: string; v: string; sub: string; tone?: string }) {
  return <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4"><dt className="text-xs text-slate-400">{k}</dt><dd className={`mt-1 text-xl font-semibold capitalize tabular-nums ${tone}`}>{v}</dd><dd className="mt-1 text-[11px] text-slate-500">{sub}</dd></div>;
}

/** Native health summary: service alerts and provider quotas. Opening it spends no provider credits. */
export async function WorkspaceSettings() {
  const [ops, odds, props] = await Promise.all([fantasyApi<Operations>("/operations/history", 5000),
    fantasyApi<Odds>("/calibration/odds-status", 5000), fantasyApi<Props>("/calibration/prop-provider-status", 5000)]);
  const healthy = ops?.status === "current";
  return <div className="space-y-8">
    <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Tile k="Service status" v={ops ? label(ops.status) : "—"} sub={ops ? `Observed ${when(ops.latest?.at)}` : "Monitoring unavailable"} tone={ops ? healthy && !ops.alerts.length ? "text-emerald-300" : "text-amber-200" : ""} />
      <Tile k="Open alerts" v={ops ? String(ops.alerts.length) : "—"} sub="Latest observation only" tone={ops?.alerts.length ? "text-amber-200" : ""} />
      <Tile k="Odds API remaining" v={odds?.telemetry?.remaining != null ? String(odds.telemetry.remaining) : "—"} sub={`Reserve floor ${odds?.quota_floor ?? "?"} · reported ${when(odds?.telemetry?.observed_at)}`} tone={odds?.quota_blocked ? "text-rose-300" : ""} />
      <Tile k="API memory peak" v={ops?.latest?.performance.peak_rss_bytes != null ? `${(ops.latest.performance.peak_rss_bytes / 1048576).toFixed(0)} MiB` : "—"} sub="This API process since restart" />
    </dl>
    <section aria-label="Alerts">
      <h2 className="text-lg font-semibold">Needs attention</h2>
      {!ops ? <p role="status" className="mt-2 rounded-xl border border-amber-800 p-4 text-sm">Monitoring is unavailable. This is a connection error, not a clean bill of health.</p>
        : ops.alerts.length ? <ul className="mt-2 space-y-2">{ops.alerts.map(a => <li key={a} className="rounded-xl border border-amber-800/70 bg-amber-500/5 p-3 text-sm text-amber-100">{a}</li>)}</ul>
        : <p className="mt-2 text-sm text-slate-400">No alerts in the latest observation. This is not a complete health certification.</p>}
    </section>
    <section aria-label="Provider collection">
      <h2 className="text-lg font-semibold">Provider collection</h2>
      <ul className="mt-3 grid gap-3 md:grid-cols-2">
        <li className="rounded-xl border border-slate-800 p-4 text-sm">
          <h3 className="font-semibold">The Odds API <span className="text-xs font-normal text-slate-500">{odds?.configured == null ? "unknown" : odds.configured ? "configured" : "not configured"}{odds?.quota_blocked ? " · quota guard blocking" : ""}</span></h3>
          <ul className="mt-2 space-y-1 text-xs text-slate-400">{(odds?.sports ?? []).map(s => <li key={s.sport}><span className="uppercase text-slate-300">{s.sport}</span> · {label(s.reason)}{s.window_opens_at ? ` · window opens ${when(s.window_opens_at)}` : ""}</li>)}</ul>
        </li>
        {Object.entries(props?.providers ?? {}).map(([key, p]) => <li key={key} className="rounded-xl border border-slate-800 p-4 text-sm">
          <h3 className="font-semibold">{key === "sgo" ? "SportsGameOdds" : key.startsWith("parlay") ? "ParlayAPI" : key} <span className="text-xs font-normal text-slate-500">{p.configured ? "configured" : "not configured"}{props?.enabled === false ? " · collection disabled" : ""}</span></h3>
          <p className="mt-2 flex justify-between text-xs text-slate-400"><span>Reserved today (UTC)</span><span className="tabular-nums">{p.reserved_today} / {p.daily_limit} {p.unit}</span></p>
          <span aria-hidden="true" className="mt-1 block h-2 rounded bg-slate-800"><span className="block h-2 rounded bg-emerald-400" style={{ width: `${Math.min(100, (p.reserved_today / Math.max(1, p.daily_limit)) * 100)}%` }} /></span>
          {p.blocked_seconds > 0 && <p className="mt-1 text-xs text-amber-200">Blocked for {p.blocked_seconds}s</p>}
        </li>)}
      </ul>
    </section>
  </div>;
}
