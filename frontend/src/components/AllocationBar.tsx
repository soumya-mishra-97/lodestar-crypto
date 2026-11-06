import type { AllocationSlice } from "@/api/types";
import { usd } from "@/lib/format";

const MAX_PARTS = 6; // tall segmented bar: <= 6 parts, the tail folds into "Other"

function parts(slices: AllocationSlice[]) {
  const valued = slices.filter((s) => s.value_usd > 0).sort((a, b) => b.value_usd - a.value_usd);
  const total = valued.reduce((sum, s) => sum + s.value_usd, 0);
  const head = valued.length > MAX_PARTS ? valued.slice(0, MAX_PARTS - 1) : valued;
  const out = head.map((s, i) => ({
    name: s.asset.symbol,
    value: s.value_usd,
    // Color follows the entity's slot; "Other" is neutral, never a generated hue.
    color: s.asset.id === "other" ? "var(--muted)" : `var(--series-${i + 1})`,
  }));
  const rest = valued.slice(head.length).reduce((sum, s) => sum + s.value_usd, 0);
  if (rest > 0) out.push({ name: "Other", value: rest, color: "var(--muted)" });
  return { out, total };
}

/**
 * Part-to-whole. `tall`: standalone in a card, share printed on each block, legend of names.
 * `thin`: above a table that already lists the figures, so no text on the bar.
 */
export function AllocationBar({ slices, variant = "tall" }: { slices: AllocationSlice[]; variant?: "tall" | "thin" }) {
  const { out, total } = parts(slices);
  if (total === 0) return null;
  const share = (v: number) => (v / total) * 100;
  return (
    <figure>
      <div
        className={`flex w-full gap-0.5 ${variant === "tall" ? "h-9" : "h-2"}`}
        role="img"
        aria-label={out.map((p) => `${p.name} ${share(p.value).toFixed(1)}%`).join(", ")}
      >
        {out.map((p) => (
          <div
            key={p.name}
            title={`${p.name}: ${usd(p.value)} (${share(p.value).toFixed(1)}%)`}
            className="flex h-full items-center justify-center overflow-hidden rounded-[4px] text-[11px] font-medium text-white"
            style={{ width: `${share(p.value)}%`, background: p.color }}
          >
            {variant === "tall" && share(p.value) >= 9 ? `${share(p.value).toFixed(0)}%` : ""}
          </div>
        ))}
      </div>
      <figcaption className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
        {out.map((p) => (
          <span key={p.name} className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm" style={{ background: p.color }} aria-hidden />
            {p.name}
            {variant === "tall" && <span className="tabular text-muted">{usd(p.value, { compact: true })}</span>}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

/** 30-day close sparkline in the de-emphasis hue; the last point is marked in the accent. */
export function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) return <span className="text-xs text-muted">—</span>;
  const w = 96;
  const h = 28;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const x = (i: number) => (i / (values.length - 1)) * (w - 4) + 2;
  const y = (v: number) => (max === min ? h / 2 : h - 3 - ((v - min) / (max - min)) * (h - 6));
  const d = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const last = values.at(-1) ?? 0;
  const first = values[0] ?? last;
  return (
    <svg width={w} height={h} role="img" aria-label={`${label}: 30-day trend ${last >= first ? "up" : "down"} ${(((last - first) / first) * 100).toFixed(1)}%`}>
      <path d={d} fill="none" stroke="var(--muted)" strokeWidth={1.5} strokeLinejoin="round" />
      <circle cx={x(values.length - 1)} cy={y(last)} r={2.5} fill="var(--accent)" />
    </svg>
  );
}
