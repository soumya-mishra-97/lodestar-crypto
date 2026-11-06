import type { ReportKind, RunEvent, RunStatus } from "@/api/types";

export const ANALYSTS = ["technical", "fundamental", "sentiment", "risk"] as const;
export const STEP_ORDER = ["data", ...ANALYSTS, "portfolio", "report_writer", "verifier", "human_approval"] as const;

/** Trader-skills run: five skills in parallel, then the engines one after another. */
export const TRADE_SKILLS = ["technical_analyst", "fundamentals_analyst", "sentiment_reader", "news_event_scout", "liquidity_checker"] as const;
export const TRADE_ENGINES = ["timing_agent", "scenario_stats_engine", "risk_position_sizer", "backtester"] as const;
export const TRADE_STEP_ORDER = ["data", ...TRADE_SKILLS, ...TRADE_ENGINES, "report_writer", "verifier", "human_approval"] as const;

export interface StepLayout {
  parallel: readonly string[];
  parallelLabel: string;
  after: readonly string[];
}

export function stepLayout(kind: ReportKind = "on_demand"): StepLayout {
  const tail = ["report_writer", "verifier", "human_approval", "fail_closed"];
  return kind === "trade_plan"
    ? { parallel: TRADE_SKILLS, parallelLabel: "Five skills run in parallel with read-only tools", after: [...TRADE_ENGINES, ...tail] }
    : { parallel: ANALYSTS, parallelLabel: "Analysts run in parallel", after: ["portfolio", ...tail] };
}

export const STEP_LABEL: Record<string, string> = {
  data: "Data",
  technical: "Technical analyst",
  fundamental: "Fundamental analyst",
  sentiment: "Sentiment analyst",
  risk: "Risk analyst",
  portfolio: "Portfolio",
  report_writer: "Report writer",
  verifier: "Verifier",
  human_approval: "Human approval",
  fail_closed: "Fail closed",
  technical_analyst: "Technical analyst",
  fundamentals_analyst: "Fundamentals analyst",
  sentiment_reader: "Sentiment reader",
  news_event_scout: "News and event scout",
  liquidity_checker: "Liquidity checker",
  timing_agent: "Timing agent",
  scenario_stats_engine: "Scenario stats engine",
  risk_position_sizer: "Risk and position sizer",
  backtester: "Backtester",
};

export type StepState = "pending" | "running" | "completed" | "failed" | "waiting";

export interface Attempt {
  attempt: number | null;
  state: StepState;
  startedAt: string;
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  evidenceIds: string[];
  durationMs?: number;
  message?: string;
}

export interface StepView {
  step: string;
  state: StepState;
  attempts: Attempt[];
  toolCalls: RunEvent[];
  notes: RunEvent[];
}

export interface Timeline {
  steps: StepView[];
  runStatus: RunStatus | null;
  runMessage: string | null;
  lastSeq: number;
}

const asRecord = (v: unknown) => (v && typeof v === "object" ? (v as Record<string, unknown>) : undefined);
const asIds = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** Fold a run's event log into per-step views. Pure: replaying the same events gives the same timeline. */
export function buildTimeline(events: RunEvent[], kind: ReportKind = "on_demand"): Timeline {
  const order: readonly string[] = kind === "trade_plan" ? TRADE_STEP_ORDER : STEP_ORDER;
  const steps = new Map<string, StepView>(order.map((s) => [s, { step: s, state: "pending", attempts: [], toolCalls: [], notes: [] }]));
  let runStatus: RunStatus | null = null;
  let runMessage: string | null = null;
  let lastSeq = 0;

  const sorted = [...events].sort((a, b) => a.seq - b.seq);
  const seen = new Set<number>();
  for (const e of sorted) {
    if (seen.has(e.seq)) continue;
    seen.add(e.seq);
    lastSeq = Math.max(lastSeq, e.seq);
    if (e.type === "run") {
      runStatus = e.status as RunStatus;
      runMessage = typeof e.payload.message === "string" ? e.payload.message : runMessage;
      continue;
    }
    let view = steps.get(e.step);
    if (!view) {
      view = { step: e.step, state: "pending", attempts: [], toolCalls: [], notes: [] };
      steps.set(e.step, view);
    }
    if (e.type === "tool_call") view.toolCalls.push(e);
    else if (e.type === "note") view.notes.push(e);
    else if (e.type === "step") {
      const p = e.payload;
      const state = (e.status ?? "pending") as StepState;
      const attemptNo = typeof p.attempt === "number" ? p.attempt : null;
      if (state === "running" || state === "waiting") {
        view.attempts.push({ attempt: attemptNo, state, startedAt: e.ts, inputs: asRecord(p.inputs), evidenceIds: [], message: p.message as string | undefined });
      } else {
        const current = view.attempts.at(-1);
        const update = {
          state,
          outputs: asRecord(p.outputs),
          evidenceIds: asIds(p.evidence_ids),
          durationMs: typeof p.duration_ms === "number" ? p.duration_ms : undefined,
          message: typeof p.message === "string" ? p.message : undefined,
        };
        if (current && (current.state === "running" || current.state === "waiting")) Object.assign(current, update);
        else view.attempts.push({ attempt: attemptNo, startedAt: e.ts, ...update });
      }
      view.state = state;
    }
  }
  return { steps: [...steps.values()].filter((s) => s.step !== "fail_closed" || s.attempts.length), runStatus, runMessage, lastSeq };
}

export function mergeEvents(current: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  const bySeq = new Map(current.map((e) => [e.seq, e]));
  for (const e of incoming) bySeq.set(e.seq, e);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

export const RESTING: RunStatus[] = ["awaiting_approval", "approved", "rejected", "failed"];
