import type { PaperStatus, SetupKind } from "@/api/types";

export const SETUP_LABEL: Record<SetupKind, string> = {
  breakout: "Breakout",
  pullback: "Pullback in an uptrend",
  trend_reclaim: "Trend reclaim",
};

export const ACTIVE_PAPER: PaperStatus[] = ["pending", "triggered", "open"];

/** Map price levels onto a 0-100% track with a small margin, so the ladder never clips its end marks. */
export function ladderScale(levels: number[], margin = 0.02): (v: number) => number {
  const lo = Math.min(...levels) * (1 - margin);
  const hi = Math.max(...levels) * (1 + margin);
  const span = hi - lo || 1;
  return (v: number) => Math.max(0, Math.min(100, ((v - lo) / span) * 100));
}
