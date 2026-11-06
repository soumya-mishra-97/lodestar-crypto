import { ChevronRight, Wrench } from "lucide-react";
import type { RunEvent } from "@/api/types";
import type { ReportKind } from "@/api/types";
import { type Attempt, STEP_LABEL, stepLayout, type StepView, type Timeline as TimelineData } from "@/lib/pipeline";
import { duration } from "@/lib/format";
import { IdChip, StatusBadge } from "./ui";

function Json({ value }: { value: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto rounded-md bg-page p-2 text-[11px] leading-snug text-ink-2">
      {JSON.stringify(value, null, 1)}
    </pre>
  );
}

function Ids({ ids, max = 24 }: { ids: string[]; max?: number }) {
  if (!ids.length) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {ids.slice(0, max).map((id) => (
        <IdChip key={id} id={id} />
      ))}
      {ids.length > max && <span className="text-[11px] text-muted">+{ids.length - max} more</span>}
    </div>
  );
}

function ToolCall({ e }: { e: RunEvent }) {
  const p = e.payload as { react_step?: number; max_steps?: number; tool?: string; args?: object; observation?: object; evidence_ids?: string[] };
  return (
    <li className="rounded-md border border-line p-2">
      <details>
        <summary className="flex cursor-pointer items-center gap-2 text-xs">
          <span className="tabular text-muted">
            step {p.react_step}/{p.max_steps}
          </span>
          <Wrench size={12} className="text-muted" aria-hidden />
          <code className="text-ink">
            {p.tool}({Object.entries(p.args ?? {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})
          </code>
          {e.status === "error" && <span className="text-critical">error</span>}
          <span className="ml-auto">
            <Ids ids={p.evidence_ids ?? []} max={6} />
          </span>
        </summary>
        <div className="mt-2">
          <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">Observation</div>
          <Json value={p.observation} />
        </div>
      </details>
    </li>
  );
}

function AttemptBody({ a, showAttempt }: { a: Attempt; showAttempt: boolean }) {
  const findings = (a.outputs?.findings as string[] | undefined) ?? [];
  return (
    <div className="space-y-2 text-xs">
      {showAttempt && (
        <div className="flex items-center gap-2 text-ink-2">
          Attempt {a.attempt} <StatusBadge status={a.state} /> <span className="text-muted">{duration(a.durationMs)}</span>
        </div>
      )}
      {a.message && <p className="text-ink-2">{a.message}</p>}
      {findings.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-critical">
          {findings.slice(0, 8).map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      )}
      <Ids ids={a.evidenceIds} />
      <div className="grid gap-2 md:grid-cols-2">
        {a.inputs && (
          <div>
            <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">Inputs</div>
            <Json value={a.inputs} />
          </div>
        )}
        {a.outputs && (
          <div>
            <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">Outputs</div>
            <Json value={a.outputs} />
          </div>
        )}
      </div>
    </div>
  );
}

function StepCard({ view, compact = false }: { view: StepView; compact?: boolean }) {
  const last = view.attempts.at(-1);
  const multiple = view.attempts.length > 1;
  return (
    <details className="group rounded-lg border border-line bg-surface p-3" open={view.state === "running" || view.state === "failed" || undefined}>
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-2 gap-y-1">
        <ChevronRight size={14} className="text-muted transition group-open:rotate-90" aria-hidden />
        <span className="whitespace-nowrap text-sm font-medium text-ink">{STEP_LABEL[view.step] ?? view.step}</span>
        <StatusBadge status={view.state} />
        <span className="ml-auto flex flex-wrap items-center justify-end gap-x-2 text-xs text-muted [&>*]:whitespace-nowrap">
          {view.toolCalls.length > 0 && <span>{view.toolCalls.length} tool calls</span>}
          {multiple && <span>{view.attempts.length} attempts</span>}
          {last?.evidenceIds.length ? <span>{last.evidenceIds.length} evidence</span> : null}
          {last?.durationMs !== undefined && <span>{duration(last.durationMs)}</span>}
        </span>
      </summary>
      <div className={`mt-3 space-y-3 ${compact ? "" : "pl-5"}`}>
        {view.notes.map((n) => (
          <p key={n.seq} className="rounded-md border px-2 py-1 text-xs text-ink" style={{ borderColor: "var(--warning)" }}>
            ⚠ {String(n.payload.message ?? "")}
          </p>
        ))}
        {view.toolCalls.length > 0 && (
          <div>
            <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">ReAct steps (read-only tools)</div>
            <ol className="space-y-1">
              {view.toolCalls.map((e) => (
                <ToolCall key={e.seq} e={e} />
              ))}
            </ol>
          </div>
        )}
        {view.attempts.map((a, i) => (
          <AttemptBody key={i} a={a} showAttempt={multiple} />
        ))}
        {!view.attempts.length && <p className="text-xs text-muted">Not started.</p>}
      </div>
    </details>
  );
}

export function Timeline({ timeline, kind = "on_demand" }: { timeline: TimelineData; kind?: ReportKind }) {
  const by = new Map(timeline.steps.map((s) => [s.step, s]));
  const get = (s: string) => by.get(s);
  const layout = stepLayout(kind);
  const analysts = layout.parallel.map(get).filter((s): s is StepView => Boolean(s));
  const after = layout.after.map(get).filter((s): s is StepView => Boolean(s));
  const data = get("data");
  return (
    <ol className="space-y-3" aria-label="Pipeline steps">
      {data && (
        <li>
          <StepCard view={data} />
        </li>
      )}
      <li>
        <div className="mb-2 text-xs text-muted">{layout.parallelLabel}</div>
        <div className={`grid gap-3 lg:grid-cols-2 ${analysts.length > 4 ? "2xl:grid-cols-3" : ""}`}>
          {analysts.map((a) => (
            <StepCard key={a.step} view={a} compact />
          ))}
        </div>
      </li>
      {after
        .filter((s) => s.step !== "fail_closed" || s.attempts.length)
        .map((s) => (
          <li key={s.step}>
            <StepCard view={s} />
          </li>
        ))}
    </ol>
  );
}
