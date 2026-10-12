export default function Loading() {
  return <main className="mx-auto max-w-7xl p-6" aria-busy="true" aria-live="polite">
    <h1 className="text-3xl font-semibold">Opening your workspace</h1>
    <p className="mt-3 text-slate-300">Reading saved league context. No forecast is being rebuilt by this page.</p>
  </main>;
}
