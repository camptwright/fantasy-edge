"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { WORKSPACES, workspaceHref, workspaceView, fantasyHref } from "@/lib/workspace";

export function WorkspaceNav() {
  const query = useSearchParams();
  const [pending, setPending] = useState(false);
  const active = workspaceView(query.get("view") ?? undefined);
  const league = query.get("league") ?? undefined;
  return <header className="border-b border-slate-800 bg-slate-950">
    <a href="#workspace-content" className="sr-only focus:not-sr-only focus:block focus:p-3">Skip to content</a>
    <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-5 py-4">
      <Link href={workspaceHref("today", league)} prefetch={false} className="font-semibold text-emerald-300">Fantasy Edge <span className="text-xs text-slate-400">Preview</span></Link>
      <Link href={fantasyHref("/fantasy", league)} prefetch={false} className="text-sm text-slate-300 underline underline-offset-4">Return to current app</Link>
      <nav aria-label="Workspaces" aria-busy={pending} className="workspace-scrollbar flex w-full gap-2 overflow-x-auto">
        {/* Full document loads avoid the observed stuck query-only RSC return transition. */}
        {WORKSPACES.map(view => <a key={view.id} href={workspaceHref(view.id, league)}
          onClick={event => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            setPending(true);
          }}
          aria-current={active === view.id ? "page" : undefined}
          className={`min-h-11 rounded-lg px-4 py-3 text-sm ${active === view.id ? "bg-emerald-950 text-emerald-200" : "text-slate-300 hover:bg-slate-900"}`}>{view.label}</a>)}
      </nav>
      <p role="status" aria-live="polite" className={pending ? 'text-xs text-slate-400' : 'sr-only'}>{pending ? 'Opening workspace…' : ''}</p>
    </div>
  </header>;
}
