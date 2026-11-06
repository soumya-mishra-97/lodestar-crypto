import type { Evidence } from "@/api/types";

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });

/** Prices span $70,000 (BTC) to $0.00001 (memecoins): keep ~4 significant digits below $1. */
export function usd(value: number | null | undefined, opts: { compact?: boolean } = {}): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (opts.compact && abs >= 10_000) return `${value < 0 ? "-" : ""}$${compact.format(abs)}`;
  if (abs >= 1) return value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  if (abs === 0) return "$0.00";
  return `${value < 0 ? "-" : ""}$${abs.toPrecision(4)}`;
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function num(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return Math.abs(value) >= 10_000 ? compact.format(value) : value.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

export function evidenceValue(e: Pick<Evidence, "value" | "unit">): string {
  if (typeof e.value === "string") return e.value.replace(/_/g, " ");
  switch (e.unit) {
    case "usd":
      return usd(e.value, { compact: true });
    case "pct":
      return pct(e.value);
    case "ratio":
      return e.value.toFixed(2);
    case "index":
      return e.value.toFixed(1);
    case "days":
      return `${e.value.toFixed(0)} days`;
    default:
      return num(e.value);
  }
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  const s = Math.round((now.getTime() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86_400)}d ago`;
}

export function duration(ms: number | undefined): string {
  if (ms === undefined) return "";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export const label = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
