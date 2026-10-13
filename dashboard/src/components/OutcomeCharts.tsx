import { meterSegments } from "@/lib/workspace";
import type { PlayerRange } from "@/lib/workspace-api.generated";

const EDGE0 = -4, BIN = 2;

/** Simulated score distribution (WalterPicks-style boom/bust curve) with shaded tails. */
export function DistributionCurve({ ranges, colors, boom, bust, height = 140 }: {
  ranges: { label: string; range: PlayerRange }[]; colors: string[]; boom?: number; bust?: number; height?: number;
}) {
  const width = 320, max = Math.max(0.0001, ...ranges.flatMap(r => r.range.density));
  const x = (points: number) => ((points - EDGE0) / (BIN * 27)) * width;
  const y = (d: number) => height - 18 - (d / max) * (height - 30);
  const path = (density: number[]) => density.map((d, i) => `${i ? "L" : "M"}${x(EDGE0 + BIN * i + BIN / 2).toFixed(1)},${y(d).toFixed(1)}`).join(" ");
  return <svg viewBox={`0 0 ${width} ${height}`} className="mx-auto block w-full max-w-xl" role="img" aria-label={`Simulated score distributions: ${ranges.map(r => `${r.label} 10th to 90th percentile ${r.range.p10} to ${r.range.p90}`).join("; ")}`}>
    {bust != null && <rect x={0} y={0} width={x(bust)} height={height - 18} className="fill-rose-500/10" />}
    {boom != null && <rect x={x(boom)} y={0} width={width - x(boom)} height={height - 18} className="fill-emerald-500/10" />}
    {ranges.map((r, i) => <g key={r.label}>
      <path d={`${path(r.range.density)} L${x(50)},${height - 18} L${x(-3)},${height - 18} Z`} fill={colors[i]} fillOpacity={0.12} />
      <path d={path(r.range.density)} fill="none" stroke={colors[i]} strokeWidth={2} />
      {r.range.mean != null && <line x1={x(r.range.mean)} x2={x(r.range.mean)} y1={8} y2={height - 18} stroke={colors[i]} strokeDasharray="3 3" />}
    </g>)}
    <line x1={0} x2={width} y1={height - 18} y2={height - 18} className="stroke-slate-700" />
    {[0, 10, 20, 30, 40].map(t => <text key={t} x={x(t)} y={height - 4} textAnchor="middle" className="fill-slate-500 text-[9px]">{t}</text>)}
    {bust != null && <text x={4} y={12} className="fill-rose-300 text-[9px]">Bust ≤{bust}</text>}
    {boom != null && <text x={width - 4} y={12} textAnchor="end" className="fill-emerald-300 text-[9px]">Boom ≥{boom}</text>}
  </svg>;
}

/** Five-segment meter; `null` renders a dash (not simulated), never an empty meter. */
export function Meter({ probability, tone, label }: { probability: number | null | undefined; tone: "up" | "down"; label: string }) {
  const filled = meterSegments(probability);
  if (filled == null) return <span className="text-xs text-slate-600" title={`${label}: not simulated`}>–</span>;
  return <span role="img" aria-label={`${label} ${Math.round((probability ?? 0) * 100)}%`} title={`${label} ${Math.round((probability ?? 0) * 100)}%`} className="inline-flex gap-0.5">
    {Array.from({ length: 5 }, (_, i) => <span key={i} className={`h-1.5 w-3 rounded-full ${i < filled ? (tone === "up" ? "bg-emerald-400" : "bg-rose-400") : "bg-slate-700"}`} />)}
  </span>;
}

/** Strength-of-schedule stars (5 = easiest); unknown renders a dash, never zero stars. */
export function SosStars({ stars, label }: { stars: number | null | undefined; label: string }) {
  if (stars == null) return <span className="text-[11px] text-slate-500">{label} —</span>;
  return <span className="inline-flex items-center gap-1 text-[11px] text-slate-400" aria-label={`${label}: ${stars} of 5 stars, 5 is easiest`}>
    {label}<span aria-hidden="true" className="tracking-tight text-amber-300">{"★".repeat(stars)}<span className="text-slate-700">{"★".repeat(5 - stars)}</span></span>
  </span>;
}
