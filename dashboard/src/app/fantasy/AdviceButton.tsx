"use client";

import { useState } from "react";

type AdviceResponse = { advice: string } | { error?: string; detail?: string };

// The local model is genuinely slow the first time it's asked anything
// after being idle (observed up to ~190s to load into Ollama's memory
// and generate) and much faster once warm (~10-20s) - shown as a
// realistic status message rather than a generic spinner so a long wait
// doesn't read as broken.
export function AdviceButton({ leagueId }: { leagueId: string }) {
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [text, setText] = useState("");

  async function run() {
    setState("loading");
    setText("");
    try {
      const response = await fetch("/api/fantasy/advice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ league_id: leagueId }),
      });
      const body: AdviceResponse = await response.json();
      if (!response.ok || !("advice" in body)) {
        setText(("detail" in body && body.detail) || ("error" in body && body.error) || `Request failed (${response.status}).`);
        setState("error");
        return;
      }
      setText(body.advice);
      setState("done");
    } catch {
      setText("Could not reach the advice service.");
      setState("error");
    }
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <h2 className="font-semibold">AI start/sit &amp; waiver read</h2>
          <p className="mt-1 text-xs text-slate-500">Local model, grounded only in the lineup/waiver/news evidence above - can take up to a few minutes the first time.</p>
        </div>
        <button
          type="button"
          onClick={run}
          disabled={state === "loading"}
          className="shrink-0 rounded-lg border border-emerald-700 bg-emerald-950/40 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-950/70 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {state === "loading" ? "Generating…" : state === "done" ? "Regenerate" : "Get AI read"}
        </button>
      </div>
      {state === "loading" && <p className="mt-4 text-sm text-slate-400">Running the local model on tonight&apos;s lineup - this can take a couple of minutes if it hasn&apos;t run recently.</p>}
      {(state === "done" || state === "error") && (
        <pre className={`mt-4 whitespace-pre-wrap rounded-lg border p-4 text-sm ${state === "error" ? "border-red-900 bg-red-950/30 text-red-200" : "border-slate-800 bg-slate-950 text-slate-200"}`}>
          {text}
        </pre>
      )}
    </section>
  );
}
