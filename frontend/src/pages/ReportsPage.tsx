import { useState } from "react";
import { Link, useParams } from "react-router";
import { useReport, useReports } from "@/api/hooks";
import { isTradePlan, type ReportKind, type ReportStatus } from "@/api/types";
import { ReportView } from "@/components/ReportView";
import { SetupBadge, TradePlanView } from "@/components/TradePlanView";
import { Card, Empty, RiskBadge, Spinner, StanceBadge, StatusBadge } from "@/components/ui";
import { relativeTime } from "@/lib/format";

const KINDS: [ReportKind | "all", string][] = [
  ["all", "All"],
  ["daily", "Daily"],
  ["on_demand", "On-demand"],
  ["trade_plan", "Trade plans"],
];
const KIND_TEXT: Record<ReportKind, string> = { daily: "Daily", on_demand: "On-demand", trade_plan: "Trade plan" };
const STATUSES: [ReportStatus | "all", string][] = [
  ["all", "Any status"],
  ["pending_approval", "Pending approval"],
  ["approved", "Approved"],
  ["rejected", "Rejected"],
];

function Segmented<T extends string>({ options, value, onChange, label }: { options: [T, string][]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div className="flex gap-1" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button
          key={v}
          type="button"
          aria-pressed={value === v}
          onClick={() => onChange(v)}
          className={`rounded-md px-2.5 py-1 text-xs ${value === v ? "bg-surface-2 font-semibold text-ink" : "text-ink-2 hover:bg-surface-2"}`}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

export function ReportsPage() {
  const [kind, setKind] = useState<ReportKind | "all">("all");
  const [status, setStatus] = useState<ReportStatus | "all">("all");
  const reports = useReports(kind, status);
  return (
    <Card
      title="Reports"
      action={
        <div className="flex flex-wrap gap-3">
          <Segmented options={KINDS} value={kind} onChange={setKind} label="Report type" />
          <Segmented options={STATUSES} value={status} onChange={setStatus} label="Report status" />
        </div>
      }
    >
      {reports.isLoading ? (
        <Spinner />
      ) : !reports.data?.length ? (
        <Empty>No reports match. Watchlisted coins get a daily report; any coin can be analysed on demand or turned into a trade plan from the scanner.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {reports.data.map((r) => (
            <li key={r.id} className="py-4">
              <div className="flex flex-wrap items-center gap-2">
                <Link to={`/reports/${r.id}`} className="font-medium hover:text-accent">
                  {r.asset?.name ?? "Unknown asset"}
                </Link>
                <StatusBadge status={r.status} />
                <span className="text-xs text-muted">{KIND_TEXT[r.kind]}</span>
                <span className="ml-auto text-xs text-muted">{relativeTime(r.created_at)}</span>
              </div>
              <p className="mt-2 text-sm text-ink-2">{r.headline}</p>
              {r.kind === "trade_plan" ? (
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-ink-2">
                  <SetupBadge kind={r.setup_kind} status={r.setup_status} /> <RiskBadge level={r.short_term_risk} />
                </div>
              ) : (
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-ink-2">
                  Short <StanceBadge stance={r.short_term_stance} /> <RiskBadge level={r.short_term_risk} />
                  <span className="ml-3">Long</span> <StanceBadge stance={r.long_term_stance} /> <RiskBadge level={r.long_term_risk} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function ReportDetailPage() {
  const { reportId } = useParams();
  const report = useReport(reportId);
  if (report.isLoading) return <Spinner />;
  if (!report.data) return <Empty>Report not found. {report.error?.message}</Empty>;
  const asset = report.data.content.asset;
  return (
    <div className="space-y-4">
      <div className="text-sm text-ink-2">
        <Link to="/reports" className="text-accent">Reports</Link> /{" "}
        <Link to={`/coins/${asset.id}`} className="hover:text-accent">{asset.name}</Link>
      </div>
      {isTradePlan(report.data) ? <TradePlanView report={report.data} /> : <ReportView report={report.data} />}
    </div>
  );
}
