import { Check, Database, Download, FileText, ShieldAlert, ShieldCheck, TrendingUp, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { download } from "@/api/client";
import { useDecision } from "@/api/hooks";
import type { AnalysisReport, Assessment, Claim, Evidence, EvidenceKind, HorizonNarrative, Report } from "@/api/types";
import { evidenceValue, label, pct, relativeTime, usd } from "@/lib/format";
import { Button, Card, IdChip, inputClass, Meter, RiskBadge, StanceBadge, StatusBadge, TagBadge } from "./ui";

export type EvidenceMap = Map<string, Evidence>;

export function ClaimList({ claims, evidence, empty = "No claims in this section." }: { claims: Claim[]; evidence: EvidenceMap; empty?: string }) {
  if (!claims.length) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <ul className="space-y-2.5">
      {claims.map((c, i) => (
        <li key={i} className="flex gap-2.5 text-sm leading-relaxed text-ink">
          <TagBadge tag={c.tag} />
          <span>
            {c.text}{" "}
            <span className="inline-flex flex-wrap gap-1 align-middle">
              {c.evidence_ids.map((id) => {
                const e = evidence.get(id);
                return <IdChip key={id} id={id} title={e ? `${e.label}: ${evidenceValue(e)} · ${e.source}` : undefined} />;
              })}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

const SECTIONS: [keyof HorizonNarrative, string][] = [
  ["thesis", "Thesis"],
  ["opportunities", "Supporting signals"],
  ["risks", "Risks"],
  ["watch", "What to watch"],
];

function HorizonCard({ title, a, narrative, evidence }: { title: string; a: Assessment; narrative: HorizonNarrative; evidence: EvidenceMap }) {
  const maxPoints = Math.max(20, ...a.risk.factors.map((f) => f.points));
  return (
    <Card title={title} action={<StanceBadge stance={a.stance} />}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <div className="mb-1 flex items-baseline justify-between">
            <span className="text-xs text-ink-2">Signal score</span>
            <span className="text-lg font-semibold">
              {a.score.toFixed(0)}
              <span className="text-xs text-muted"> / 100</span>
            </span>
          </div>
          <Meter value={a.score} name={`${title} signal score`} />
          <div className="mt-1 text-xs text-muted">Data confidence {(a.confidence * 100).toFixed(0)}%</div>
        </div>
        <div>
          <div className="mb-1 flex items-baseline justify-between">
            <RiskBadge level={a.risk.level} />
            <span className="text-lg font-semibold">
              {a.risk.score.toFixed(0)}
              <span className="text-xs text-muted"> / 100</span>
            </span>
          </div>
          <Meter value={a.risk.score} name={`${title} risk score`} color="var(--serious)" track="var(--surface-2)" />
          <div className="mt-1 text-xs text-muted">Itemised risk model, computed in code</div>
        </div>
      </div>

      <details className="mt-4 rounded-lg bg-surface-2 p-3">
        <summary className="cursor-pointer text-xs font-medium text-ink-2">
          How this was computed ({a.signals.length} signals, {a.risk.factors.length} risk factors)
        </summary>
        <ul className="mt-2 space-y-1">
          {a.signals.map((s) => (
            <li key={s.name} className="flex justify-between gap-3 text-xs">
              <span className="text-ink-2">
                {s.detail} <span className="text-muted">{s.evidence_ids.join(", ")}</span>
              </span>
              <span className="tabular text-ink">{`${s.contribution > 0 ? "+" : ""}${s.contribution}`}</span>
            </li>
          ))}
        </ul>
        <ul className="mt-3 space-y-2">
          {a.risk.factors.map((f) => (
            <li key={f.name}>
              <div className="mb-1 flex justify-between text-xs">
                <span className="text-ink-2">
                  {label(f.name)} <span className="text-muted">· {f.detail}</span>
                </span>
                <span className="tabular text-ink">{f.points} pts</span>
              </div>
              <div className="h-1.5 rounded-full bg-page">
                <div className="h-full rounded-r-[4px]" style={{ width: `${(f.points / maxPoints) * 100}%`, background: "var(--muted)" }} />
              </div>
            </li>
          ))}
        </ul>
      </details>

      <div className="mt-5 space-y-5">
        {SECTIONS.map(([key, name]) =>
          narrative[key].length ? (
            <div key={key}>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{name}</h3>
              <ClaimList claims={narrative[key]} evidence={evidence} />
            </div>
          ) : null,
        )}
      </div>
    </Card>
  );
}

const KIND_LABEL: Record<EvidenceKind, string> = { observation: "Observed", calculation: "Computed", text: "Untrusted text" };

export function EvidenceTable({ items, cited }: { items: Evidence[]; cited: Set<string> }) {
  const [filter, setFilter] = useState<"cited" | "all">("cited");
  const shown = filter === "cited" ? items.filter((e) => cited.has(e.id)) : items;
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Database size={16} aria-hidden /> Evidence bundle ({cited.size} cited of {items.length})
        </span>
      }
      action={
        <div className="flex gap-1" role="group" aria-label="Evidence filter">
          {(["cited", "all"] as const).map((f) => (
            <button
              key={f}
              type="button"
              aria-pressed={filter === f}
              onClick={() => setFilter(f)}
              className={`rounded-md px-2 py-1 text-xs ${filter === f ? "bg-surface-2 font-semibold text-ink" : "text-ink-2"}`}
            >
              {f === "cited" ? "Cited" : "All"}
            </button>
          ))}
        </div>
      }
    >
      <div className="max-h-[28rem] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface">
            <tr className="text-left text-xs text-muted">
              <th className="pb-2 font-normal">ID</th>
              <th className="pb-2 font-normal">Metric</th>
              <th className="pb-2 text-right font-normal">Value</th>
              <th className="pb-2 pl-4 font-normal">Kind</th>
              <th className="pb-2 pl-4 font-normal">Source</th>
            </tr>
          </thead>
          <tbody className="tabular">
            {shown.map((e) => (
              <tr key={e.id} className="border-t border-line align-top">
                <td className="py-1.5 font-mono text-xs text-muted">{e.id}</td>
                <td className="py-1.5 text-ink-2">
                  {e.label}
                  {e.inputs.length > 0 && <div className="text-[11px] text-muted">from {e.inputs.join(", ")}</div>}
                </td>
                <td className="max-w-xs py-1.5 text-right text-ink">{evidenceValue(e)}</td>
                <td className="py-1.5 pl-4 text-xs text-ink-2">{KIND_LABEL[e.kind]}</td>
                <td className="py-1.5 pl-4 text-xs text-muted">{e.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export function ApprovalBar({ report, hint }: { report: Report; hint?: string }) {
  const decide = useDecision();
  const [note, setNote] = useState("");
  if (report.status !== "pending_approval") {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-sm">
        <StatusBadge status={report.status} />
        <span className="text-ink-2">
          {report.decided_at ? `Decided ${relativeTime(report.decided_at)}` : ""}
          {report.decision_note ? ` · “${report.decision_note}”` : ""}
        </span>
      </div>
    );
  }
  return (
    <div className="rounded-xl border px-4 py-3" style={{ borderColor: "var(--warning)" }}>
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status="pending_approval" />
        <span className="text-sm text-ink-2">{hint ?? "The verifier passed this report. Review it, then approve to publish or reject it."}</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <input className={`${inputClass} max-w-md flex-1`} placeholder="Optional note" maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} aria-label="Decision note" />
        <Button onClick={() => decide.mutate({ reportId: report.id, approve: true, note })} disabled={decide.isPending}>
          <Check size={16} aria-hidden /> Approve
        </Button>
        <Button variant="danger" onClick={() => decide.mutate({ reportId: report.id, approve: false, note })} disabled={decide.isPending}>
          <X size={16} aria-hidden /> Reject
        </Button>
      </div>
      {decide.isError && <p className="mt-2 text-sm text-critical">{decide.error.message}</p>}
    </div>
  );
}

export function ExportButtons({ reportId }: { reportId: string }) {
  const [error, setError] = useState<string | null>(null);
  const run = (path: string) => download(path).catch((e: Error) => setError(e.message));
  return (
    <span className="flex items-center gap-2">
      <Button variant="ghost" onClick={() => void run(`/reports/${reportId}/export.md`)}>
        <FileText size={15} aria-hidden /> Markdown
      </Button>
      <Button variant="ghost" onClick={() => void run(`/reports/${reportId}/export.pdf`)}>
        <Download size={15} aria-hidden /> PDF
      </Button>
      {error && <span className="text-xs text-critical">{error}</span>}
    </span>
  );
}

export function ReportView({ report }: { report: AnalysisReport }) {
  const c = report.content;
  const evidence = useMemo(() => new Map(c.evidence.map((e) => [e.id, e])), [c.evidence]);
  const cited = useMemo(() => {
    const d = c.draft;
    const all = [d.headline, ...Object.values(d.short_term).flat(), ...Object.values(d.long_term).flat(), ...d.portfolio, ...d.data_quality, ...d.uncertainties];
    return new Set(all.flatMap((cl) => cl.evidence_ids));
  }, [c.draft]);
  const rec = c.reconciliation;
  const v = c.verification;

  return (
    <div className="space-y-5">
      <ApprovalBar report={report} />

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <p className="flex gap-2 text-base leading-relaxed text-ink">
              <TrendingUp size={18} className="mt-1 shrink-0 text-accent" aria-hidden />
              {c.draft.headline.text}
            </p>
            <div className="mt-2 text-xs text-muted">
              {label(report.kind)} report · generated {relativeTime(c.generated_at)} · writer: {c.draft.writer} · pipeline {c.pipeline_version} ·{" "}
              <Link to={`/pipeline/${report.run_id}`} className="text-accent">
                view run
              </Link>
            </div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <ExportButtons reportId={report.id} />
            <span className="flex items-center gap-1 text-xs text-ink-2" title="Every claim was checked against the evidence bundle">
              {v.passed ? <ShieldCheck size={14} style={{ color: "var(--good)" }} aria-hidden /> : <ShieldAlert size={14} aria-hidden />}
              Verified: {v.checked_claims} claims · {v.repairs} repair loop(s)
            </span>
          </div>
        </div>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <HorizonCard title="Short term · days to four weeks" a={c.assessments.short_term} narrative={c.draft.short_term} evidence={evidence} />
        <HorizonCard title="Long term · six months or more" a={c.assessments.long_term} narrative={c.draft.long_term} evidence={evidence} />
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <Card title="Your portfolio">
          <ClaimList claims={c.draft.portfolio} evidence={evidence} empty="No portfolio context." />
        </Card>
        <Card
          title="Data quality"
          action={rec && <span className={`text-xs ${rec.status === "mismatch" ? "text-critical" : "text-ink-2"}`}>{label(rec.status)}</span>}
        >
          {rec && (
            <table className="mb-4 w-full text-xs">
              <tbody className="tabular">
                {rec.comparisons.map((cmp) => (
                  <tr key={cmp.source} className="border-t border-line first:border-0">
                    <td className="py-1 text-ink-2">{cmp.source}</td>
                    <td className="py-1 text-right text-ink">{usd(cmp.value)}</td>
                    <td className={`py-1 text-right ${cmp.within_tolerance ? "text-muted" : "text-critical"}`}>
                      {pct(cmp.deviation_pct, 2)} {cmp.within_tolerance ? "" : "⚠"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <ClaimList claims={c.draft.data_quality} evidence={evidence} empty="No data-quality notes." />
          {c.data_gaps.length > 0 && (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-ink-2">
              {c.data_gaps.map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Assumptions and uncertainties">
          <ClaimList claims={c.draft.uncertainties} evidence={evidence} />
          <div className="mt-4 space-y-1 border-t border-line pt-3 text-xs text-ink-2">
            {Object.entries(c.analysts).map(([name, a]) => (
              <div key={name} className="flex justify-between gap-2">
                <span>{label(name)} analyst</span>
                <span className="text-muted">
                  {a.tool_calls} tool calls · {a.claims_source === "llm" ? "model" : "deterministic"} claims
                  {a.stop_reason !== "final" ? ` · ${label(a.stop_reason)}` : ""}
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <EvidenceTable items={c.evidence} cited={cited} />
      <p className="rounded-lg border border-line p-3 text-xs text-ink-2">
        <strong className="text-ink">Risk disclaimer.</strong> {c.disclaimer}
      </p>
    </div>
  );
}
