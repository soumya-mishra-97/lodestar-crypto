import { Radio } from "lucide-react";
import { useMemo } from "react";
import { Link, useParams } from "react-router";
import { useReport, useRun, useRunStream, useRuns } from "@/api/hooks";
import { isTradePlan } from "@/api/types";
import { ReportView } from "@/components/ReportView";
import { TradePlanView } from "@/components/TradePlanView";
import { Timeline } from "@/components/Timeline";
import { Card, Empty, Spinner, StatusBadge } from "@/components/ui";
import { buildTimeline } from "@/lib/pipeline";
import { relativeTime } from "@/lib/format";

function RunList({ selected }: { selected?: string }) {
  const runs = useRuns();
  if (runs.isLoading) return <Spinner />;
  if (!runs.data?.length) return <Empty>No runs yet. Add a coin with the search box to start one.</Empty>;
  return (
    <ul className="space-y-1" aria-label="Pipeline runs">
      {runs.data.map((r) => (
        <li key={r.id}>
          <Link
            to={`/pipeline/${r.id}`}
            aria-current={r.id === selected ? "page" : undefined}
            className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${r.id === selected ? "bg-surface-2" : "hover:bg-surface-2"}`}
          >
            <span className="w-12 font-medium">{r.asset?.symbol ?? "?"}</span>
            <StatusBadge status={r.status} />
            {r.kind === "trade_plan" && <span className="rounded bg-surface-2 px-1.5 text-[10px] uppercase tracking-wide text-ink-2">plan</span>}
            <span className="ml-auto whitespace-nowrap text-xs text-muted">{relativeTime(r.created_at)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function RunDetailView({ runId }: { runId: string }) {
  const run = useRun(runId);
  useRunStream(run.data);
  const timeline = useMemo(() => buildTimeline(run.data?.events ?? [], run.data?.kind), [run.data?.events, run.data?.kind]);
  const report = useReport(run.data?.report_id);
  if (run.isLoading) return <Spinner />;
  if (!run.data) return <Empty>Run not found. {run.error?.message}</Empty>;
  const r = run.data;
  const live = r.status === "queued" || r.status === "running";

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-semibold">
            {r.asset ? (
              <Link to={`/coins/${r.asset.id}`} className="hover:text-accent">
                {r.asset.name}
              </Link>
            ) : (
              "Run"
            )}
          </h1>
          <StatusBadge status={r.status} />
          {live && (
            <span className="flex items-center gap-1 text-xs text-accent">
              <Radio size={13} className="animate-pulse" aria-hidden /> Live
            </span>
          )}
          <span className="ml-auto text-xs text-muted">
            {r.kind === "trade_plan" ? "trade plan" : r.kind.replace("_", "-")} · data: {r.data_mode} · agents: {r.llm_mode} · started {relativeTime(r.created_at)}
          </span>
        </div>
        {(r.error || timeline.runMessage) && <p className="mt-2 text-sm text-critical">{r.error ?? timeline.runMessage}</p>}
        <p className="mt-2 text-xs text-muted">
          {r.kind === "trade_plan"
            ? "Every step streams its status, inputs, outputs and evidence ids. Five skills run in parallel with read-only tools and a step limit; then the timing agent, scenario statistics, position sizer and backtester compute every number in code. The verifier rejects untraceable claims, allows at most two repair loops, then fails closed. Paper trading only."
            : "Every step streams its status, inputs, outputs and evidence ids. The four analysts run in parallel with read-only tools and a step limit; the verifier allows at most two repair loops, then fails closed."}
        </p>
      </Card>

      <Timeline timeline={timeline} kind={r.kind} />

      {report.data && (
        <section aria-label="Report">
          <h2 className="mb-3 text-sm font-semibold text-ink">{isTradePlan(report.data) ? "Verified trade-plan card" : "Verified report"}</h2>
          {isTradePlan(report.data) ? <TradePlanView report={report.data} /> : <ReportView report={report.data} />}
        </section>
      )}
    </div>
  );
}

export function PipelinePage() {
  const { runId } = useParams();
  return (
    <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
      <aside>
        <h2 className="mb-2 px-1 text-sm font-semibold">Runs</h2>
        <RunList selected={runId} />
      </aside>
      <div className="min-w-0">{runId ? <RunDetailView runId={runId} /> : <Empty>Select a run to see its timeline.</Empty>}</div>
    </div>
  );
}
