"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useState } from "react";
import { FANTASY_TOOLS, WORKSPACES, fantasyTool, fantasyToolHref, routeWorkspace, workspaceHref, workspaceView, type Workspace } from "@/lib/workspace";

const ICONS: Record<Workspace, string> = {
  today: "M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10",
  fantasy: "M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.4 6.8 19.1l1-5.8L3.5 9.2l5.9-.9z",
  markets: "M4 19V9m6 10V5m6 14v-7m4 7H2",
  research: "M10 4a6 6 0 104.5 10L20 20M10 7v6m-3-3h6",
  settings: "M12 8a4 4 0 100 8 4 4 0 000-8zm8 4l2-1-2-4-2 1-2-1V5h-4v2l-2 1-2-1-2 4 2 1v2l-2 1 2 4 2-1 2 1v2h4v-2l2-1 2 1 2-4-2-1z",
};

function Icon({ view }: { view: Workspace }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={ICONS[view]} /></svg>;
}

/** Desktop rail + mobile header/tab bar. Full document loads avoid the observed stuck query-only RSC transition. */
export function WorkspaceNav() {
  const query = useSearchParams();
  const pathname = usePathname();
  const [pending, setPending] = useState(false);
  // Full tools (ledger, calibration, …) live under their workspace in the same shell.
  const active = pathname === "/workspace" ? workspaceView(query.get("view") ?? undefined) : routeWorkspace(pathname);
  const tool = fantasyTool(query.get("tool") ?? undefined);
  const league = query.get("league") ?? undefined;
  const busy = (event: React.MouseEvent) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    setPending(true);
  };
  return <>
    <a href="#workspace-content" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-slate-900 focus:p-3">Skip to content</a>
    <aside aria-label="Workspace navigation" className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-slate-800 bg-slate-950 lg:flex">
      <Link href={workspaceHref("today", league)} prefetch={false} className="flex items-center gap-2 px-5 py-5">
        <span aria-hidden="true" className="grid h-8 w-8 place-items-center rounded-lg bg-emerald-500 text-sm font-black text-slate-950">FE</span>
        <span className="font-semibold tracking-tight">Fantasy Edge</span>
      </Link>
      <nav aria-label="Workspaces" aria-busy={pending} className="flex-1 space-y-1 overflow-y-auto px-3">
        {WORKSPACES.map(view => <div key={view.id}>
          <a href={workspaceHref(view.id, league)} onClick={busy} aria-current={active === view.id && pathname === "/workspace" && (view.id !== "fantasy" || tool === "overview") ? "page" : undefined}
            className={`flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300 ${active === view.id ? "bg-slate-800/80 text-white" : "text-slate-400 hover:bg-slate-900 hover:text-slate-100"}`}>
            <Icon view={view.id} />{view.label}
          </a>
          {view.id === "fantasy" && active === "fantasy" && pathname === "/workspace" && <ul className="my-1 ml-8 space-y-0.5 border-l border-slate-800 pl-3">
            {FANTASY_TOOLS.filter(item => item.id !== "overview").map(item => <li key={item.id}><a href={fantasyToolHref(item.id, league)} onClick={busy}
              aria-current={tool === item.id ? "page" : undefined}
              className={`flex min-h-9 items-center rounded px-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300 ${tool === item.id ? "font-medium text-emerald-300" : "text-slate-400 hover:text-slate-100"}`}>{item.label}</a></li>)}
          </ul>}
        </div>)}
      </nav>
      <p className="border-t border-slate-800 px-5 py-4 text-xs text-slate-500">Research only · nothing is submitted or wagered</p>
    </aside>
    <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-800 bg-slate-950/95 px-4 py-3 backdrop-blur lg:hidden">
      <Link href={workspaceHref("today", league)} prefetch={false} className="flex items-center gap-2">
        <span aria-hidden="true" className="grid h-7 w-7 place-items-center rounded-md bg-emerald-500 text-xs font-black text-slate-950">FE</span>
        <span className="font-semibold">Fantasy Edge</span>
      </Link>
      <span className="text-[11px] text-slate-500">Research only</span>
    </header>
    <nav aria-label="Workspaces (mobile)" className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-slate-800 bg-slate-950/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
      {WORKSPACES.map(view => <a key={view.id} href={workspaceHref(view.id, league)} onClick={busy} aria-current={active === view.id ? "page" : undefined}
        className={`flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300 ${active === view.id ? "text-emerald-300" : "text-slate-400"}`}>
        <Icon view={view.id} />{view.label}
      </a>)}
    </nav>
    <p role="status" aria-live="polite" className={pending ? "fixed bottom-16 right-4 z-40 rounded bg-slate-800 px-3 py-2 text-xs text-slate-200 lg:bottom-4" : "sr-only"}>{pending ? "Opening…" : ""}</p>
  </>;
}
