import {
  AlertOctagon,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BadgeCheck,
  Brain,
  Calculator,
  CheckCircle2,
  CircleDashed,
  CircleHelp,
  Clock,
  Compass,
  Loader2,
  Minus,
  PauseCircle,
  XCircle,
} from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { ClaimTag, ReportStatus, RiskLevel, RunStatus, Stance } from "@/api/types";
import { label } from "@/lib/format";

export function Card({ title, action, children, className = "" }: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-line bg-surface p-5 ${className}`}>
      {(title || action) && (
        <header className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

/** Stat tile: label, value, optional signed delta (direction × "up is good"). */
export function StatTile({ label: l, value, delta, deltaLabel, hint }: {
  label: string;
  value: string;
  delta?: number | null;
  deltaLabel?: string;
  hint?: string;
}) {
  const up = (delta ?? 0) > 0;
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="text-xs text-ink-2">{l}</div>
      <div className="mt-1 text-2xl font-semibold text-ink">{value}</div>
      {delta !== undefined && delta !== null && (
        <div className={`mt-1 flex items-center gap-1 text-xs ${up ? "text-good-text" : "text-critical"}`}>
          {up ? <ArrowUpRight size={14} aria-hidden /> : <ArrowDownRight size={14} aria-hidden />}
          <span className="tabular">{`${up ? "+" : ""}${delta.toFixed(2)}%`}</span>
          {deltaLabel && <span className="text-muted">{deltaLabel}</span>}
        </div>
      )}
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

const STANCE = {
  favorable: { icon: ArrowUpRight, color: "var(--good)" },
  neutral: { icon: Minus, color: "var(--muted)" },
  unfavorable: { icon: ArrowDownRight, color: "var(--critical)" },
} as const;

/** Stance badge: status color + icon + label, never color alone. */
export function StanceBadge({ stance }: { stance: Stance | null | undefined }) {
  if (!stance) return <span className="text-xs text-muted">—</span>;
  const { icon: Icon, color } = STANCE[stance];
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs text-ink">
      <Icon size={13} style={{ color }} aria-hidden />
      {label(stance)}
    </span>
  );
}

const RISK = {
  low: { icon: CheckCircle2, color: "var(--good)" },
  moderate: { icon: AlertTriangle, color: "var(--warning)" },
  high: { icon: AlertTriangle, color: "var(--serious)" },
  very_high: { icon: AlertOctagon, color: "var(--critical)" },
} as const;

export function RiskBadge({ level }: { level: RiskLevel | null | undefined }) {
  if (!level) return <span className="text-xs text-muted">—</span>;
  const { icon: Icon, color } = RISK[level];
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs text-ink">
      <Icon size={13} style={{ color }} aria-hidden />
      {label(level)} risk
    </span>
  );
}

/** Meter: fill carries the value; the track is a lighter step of the same ramp. */
export function Meter({ value, max = 100, color = "var(--accent)", track = "var(--accent-track)", name }: {
  value: number;
  max?: number;
  color?: string;
  track?: string;
  name: string;
}) {
  const pctFill = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div
      role="meter"
      aria-label={name}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      className="h-2 w-full overflow-hidden rounded-full"
      style={{ background: track }}
    >
      <div className="h-full rounded-full" style={{ width: `${pctFill}%`, background: color }} />
    </div>
  );
}

export function Button({ variant = "primary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger";
}) {
  const styles = {
    primary: "bg-accent text-white hover:brightness-110",
    ghost: "border border-line text-ink hover:bg-surface-2",
    danger: "border border-line text-critical hover:bg-surface-2",
  }[variant];
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    />
  );
}

export const Spinner = ({ label: l = "Loading" }: { label?: string }) => (
  <span className="inline-flex items-center gap-2 text-sm text-ink-2" role="status">
    <Loader2 size={16} className="animate-spin" aria-hidden /> {l}
  </span>
);

export const Empty = ({ children }: { children: ReactNode }) => (
  <div className="rounded-lg border border-dashed border-line p-6 text-center text-sm text-ink-2">{children}</div>
);

export const ChangeText = ({ value }: { value: number | null | undefined }) =>
  value === null || value === undefined ? (
    <span className="text-muted">—</span>
  ) : (
    <span className={`tabular ${value > 0 ? "text-good-text" : value < 0 ? "text-critical" : "text-ink-2"}`}>
      {`${value > 0 ? "+" : ""}${value.toFixed(2)}%`}
    </span>
  );

const RUN_STATUS: Record<RunStatus | ReportStatus | "pending" | "completed" | "waiting", { icon: typeof Clock; color: string; text: string }> = {
  queued: { icon: Clock, color: "var(--muted)", text: "Queued" },
  pending: { icon: CircleDashed, color: "var(--muted)", text: "Pending" },
  running: { icon: Loader2, color: "var(--accent)", text: "Running" },
  waiting: { icon: PauseCircle, color: "var(--warning)", text: "Waiting for you" },
  awaiting_approval: { icon: PauseCircle, color: "var(--warning)", text: "Awaiting approval" },
  pending_approval: { icon: PauseCircle, color: "var(--warning)", text: "Pending approval" },
  completed: { icon: CheckCircle2, color: "var(--good)", text: "Completed" },
  approved: { icon: CheckCircle2, color: "var(--good)", text: "Approved" },
  rejected: { icon: XCircle, color: "var(--muted)", text: "Rejected" },
  failed: { icon: XCircle, color: "var(--critical)", text: "Failed" },
};

/** Run, report or step status: icon + label (never color alone). */
export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = status ? RUN_STATUS[status as keyof typeof RUN_STATUS] : undefined;
  if (!s) return <span className="text-xs text-muted">—</span>;
  const Icon = s.icon;
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-surface-2 px-2 py-0.5 text-xs text-ink">
      <Icon size={13} style={{ color: s.color }} className={status === "running" ? "animate-spin" : ""} aria-hidden />
      {s.text}
    </span>
  );
}

const TAG: Record<ClaimTag, { text: string; icon: typeof BadgeCheck; hint: string }> = {
  fact: { text: "Fact", icon: BadgeCheck, hint: "Restates a value observed from a named data provider." },
  calculation: { text: "Calculation", icon: Calculator, hint: "Restates a value computed by Lodestar code." },
  interpretation: { text: "Interpretation", icon: Brain, hint: "Reasoning over the cited evidence." },
  scenario: { text: "Scenario", icon: Compass, hint: "A conditional 'if…then' outcome, not a forecast." },
  assumption: { text: "Assumption", icon: CircleHelp, hint: "A premise or limitation of this analysis." },
};

export function TagBadge({ tag }: { tag: ClaimTag }) {
  const t = TAG[tag];
  return (
    <span
      title={t.hint}
      className="mt-0.5 inline-flex h-fit shrink-0 items-center gap-1 rounded bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ink-2"
    >
      <t.icon size={11} aria-hidden /> {t.text}
    </span>
  );
}

export function IdChip({ id, title }: { id: string; title?: string }) {
  return (
    <span
      tabIndex={0}
      title={title ?? id}
      aria-label={title ? `Evidence ${id}: ${title}` : `Evidence ${id}`}
      className="cursor-help rounded border border-line px-1 font-mono text-[10px] text-ink-2 hover:bg-surface-2"
    >
      {id}
    </span>
  );
}

export const inputClass =
  "w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink outline-none focus:border-accent";
