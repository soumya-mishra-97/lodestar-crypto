import { AlertOctagon, AlertTriangle, CheckCircle2, ClipboardList, FlaskConical, LineChart, ShieldAlert, ShieldCheck, Target } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router";
import { usePaperOpen } from "@/api/hooks";
import type { Reliability, ScenarioSet, SetupKind, SetupStatus, TradeMetrics, TradePlanCard, TradePlanReport } from "@/api/types";
import { label, pct, relativeTime, usd } from "@/lib/format";
import { ladderScale, SETUP_LABEL } from "@/lib/trading";
import { ApprovalBar, ClaimList, EvidenceTable, ExportButtons } from "./ReportView";
import { Button, Card, Meter, RiskBadge } from "./ui";

const STATUS: Record<SetupStatus, { text: string; icon: typeof Target; color: string }> = {
  active: { text: "Triggered recently, price in or below the zone", icon: Target, color: "var(--accent)" },
  extended: { text: "Extended above the entry zone", icon: AlertTriangle, color: "var(--warning)" },
  waiting: { text: "Waiting for the trigger", icon: ClipboardList, color: "var(--muted)" },
};

export function SetupBadge({ kind, status }: { kind: SetupKind | null | undefined; status?: SetupStatus | null }) {
  if (!kind) return <span className="text-xs text-muted">—</span>;
  const s = status ? STATUS[status] : null;
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-surface-2 px-2 py-0.5 text-xs text-ink" title={s?.text}>
      {s && <s.icon size={13} style={{ color: s.color }} aria-hidden />}
      {SETUP_LABEL[kind]}
      {status && <span className="text-muted">· {status}</span>}
    </span>
  );
}

const RELIABILITY: Record<Reliability, { text: string; icon: typeof CheckCircle2; color: string }> = {
  insufficient: { text: "Too few cases to trust", icon: AlertOctagon, color: "var(--critical)" },
  small: { text: "Small sample: treat with caution", icon: AlertTriangle, color: "var(--warning)" },
  adequate: { text: "Adequate sample", icon: CheckCircle2, color: "var(--good)" },
};

export function ReliabilityBadge({ value, n }: { value: Reliability; n: number }) {
  const r = RELIABILITY[value];
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs text-ink">
      <r.icon size={13} style={{ color: r.color }} aria-hidden />
      {r.text} (n = {n})
    </span>
  );
}

/** Price ladder: invalidation, entry zone, trigger, last close and the profit-taking rule on one scale. */
function Ladder({ card }: { card: TradePlanCard }) {
  const t = card.timing;
  const close = card.setup.close;
  const scale = ladderScale([t.invalidation, t.profit_level, close]);
  const x = (v: number) => `${scale(v)}%`;
  const marks = [
    { v: t.invalidation, text: "Invalidation", color: "var(--critical)" },
    { v: t.trigger_level, text: "Trigger", color: "var(--accent)" },
    { v: t.profit_level, text: "Profit rule", color: "var(--good)" },
  ];
  return (
    <div aria-hidden className="relative mt-2 h-16">
      <div className="absolute inset-x-0 top-7 h-1.5 rounded-full bg-surface-2" />
      <div
        className="absolute top-6 h-3.5 rounded"
        style={{ left: x(t.entry_zone[0]), width: `calc(${x(t.entry_zone[1])} - ${x(t.entry_zone[0])})`, background: "var(--accent-track)" }}
      />
      {marks.map((m) => (
        <div key={m.text} className="absolute top-4 flex -translate-x-1/2 flex-col items-center" style={{ left: x(m.v) }}>
          <span className="h-6 w-0.5" style={{ background: m.color }} />
          <span className="mt-1 whitespace-nowrap text-[10px] text-ink-2">{m.text}</span>
        </div>
      ))}
      <div className="absolute top-0 flex -translate-x-1/2 flex-col items-center" style={{ left: x(close) }}>
        <span className="whitespace-nowrap text-[10px] text-ink">Last close</span>
        <span className="mt-0.5 h-3 w-3 rounded-full border-2 border-surface bg-[var(--ink)]" />
      </div>
    </div>
  );
}

function Row({ k, v, strong = false }: { k: string; v: string; strong?: boolean }) {
  return (
    <div className="flex justify-between gap-3 border-t border-line py-1.5 text-sm first:border-0">
      <dt className="text-ink-2">{k}</dt>
      <dd className={`tabular text-right ${strong ? "font-semibold text-ink" : "text-ink"}`}>{v}</dd>
    </div>
  );
}

const ci = (c: [number, number] | null) => (c ? `${c[0].toFixed(0)}–${c[1].toFixed(0)}%` : "—");

export function ScenarioTable({ s }: { s: ScenarioSet }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="pb-2 font-normal">Scenario</th>
            <th className="pb-2 text-right font-normal">Cases</th>
            <th className="pb-2 pl-4 font-normal">Frequency · 95% interval</th>
            <th className="pb-2 text-right font-normal">Mean</th>
            <th className="pb-2 text-right font-normal">Median</th>
            <th className="pb-2 text-right font-normal">Worst drawdown</th>
          </tr>
        </thead>
        <tbody className="tabular">
          {s.scenarios.map((r) => (
            <tr key={r.name} className="border-t border-line align-top">
              <td className="py-2">
                <div className="font-medium capitalize text-ink">{r.name}</div>
                <div className="text-[11px] text-muted">{r.definition}</div>
              </td>
              <td className="py-2 text-right text-ink-2">
                {r.count}/{r.total}
              </td>
              <td className="py-2 pl-4">
                <div className="flex items-center gap-2">
                  <span className="w-12 text-ink">{r.probability_pct === null ? "—" : `${r.probability_pct.toFixed(0)}%`}</span>
                  {r.probability_ci && (
                    <span className="relative h-1.5 w-28 rounded-full bg-surface-2" title={`95% interval ${ci(r.probability_ci)}`}>
                      <span
                        className="absolute h-full rounded-full"
                        style={{ left: `${r.probability_ci[0]}%`, width: `${r.probability_ci[1] - r.probability_ci[0]}%`, background: "var(--accent-track)" }}
                      />
                      {r.probability_pct !== null && (
                        <span className="absolute -top-0.5 h-2.5 w-0.5 rounded bg-[var(--accent)]" style={{ left: `${r.probability_pct}%` }} />
                      )}
                    </span>
                  )}
                  <span className="text-[11px] text-muted">{ci(r.probability_ci)}</span>
                </div>
              </td>
              <td className="py-2 text-right text-ink">{pct(r.mean_pct)}</td>
              <td className="py-2 text-right text-ink">{pct(r.median_pct)}</td>
              <td className="py-2 text-right text-ink-2">{pct(r.worst_drawdown_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MetricsTable({ rows }: { rows: [string, TradeMetrics | null][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="pb-2 font-normal">Sample</th>
            <th className="pb-2 text-right font-normal">Trades</th>
            <th className="pb-2 text-right font-normal">Win rate</th>
            <th className="pb-2 text-right font-normal">Total return</th>
            <th className="pb-2 text-right font-normal">Buy and hold</th>
            <th className="pb-2 text-right font-normal">Max drawdown</th>
            <th className="pb-2 text-right font-normal">Sharpe</th>
            <th className="pb-2 text-right font-normal">Exposure</th>
          </tr>
        </thead>
        <tbody className="tabular">
          {rows.map(([name, m]) => (
            <tr key={name} className="border-t border-line">
              <td className="py-1.5 text-ink-2">{name}</td>
              {m ? (
                <>
                  <td className="py-1.5 text-right">{m.trades}</td>
                  <td className="py-1.5 text-right">{m.win_rate_pct === null ? "—" : `${m.win_rate_pct.toFixed(0)}%`}</td>
                  <td className="py-1.5 text-right">{pct(m.total_return_pct)}</td>
                  <td className="py-1.5 text-right text-ink-2">{pct(m.buy_hold_return_pct)}</td>
                  <td className="py-1.5 text-right text-ink-2">{pct(m.max_drawdown_pct)}</td>
                  <td className="py-1.5 text-right">{m.sharpe.toFixed(2)}</td>
                  <td className="py-1.5 text-right text-ink-2">{m.exposure_pct.toFixed(0)}%</td>
                </>
              ) : (
                <td colSpan={7} className="py-1.5 text-right text-muted">
                  Not enough history for walk-forward folds
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Warnings({ items, title = "Warnings" }: { items: string[]; title?: string }) {
  if (!items.length) return null;
  return (
    <div className="rounded-lg border p-3" style={{ borderColor: "var(--warning)" }}>
      <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-ink">
        <AlertTriangle size={14} style={{ color: "var(--warning)" }} aria-hidden /> {title}
      </div>
      <ul className="list-disc space-y-0.5 pl-5 text-xs text-ink-2">
        {items.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
    </div>
  );
}

function PaperTradeButton({ report }: { report: TradePlanReport }) {
  const open = usePaperOpen();
  if (report.status !== "approved") {
    return <span className="text-xs text-muted">Approve the plan to paper trade it.</span>;
  }
  if (open.isSuccess) {
    return (
      <Link to="/paper" className="text-sm text-accent">
        Paper position created: waiting for the trigger. Open the paper portfolio →
      </Link>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Button onClick={() => open.mutate(report.id)} disabled={open.isPending || report.content.card.size.units <= 0}>
        <FlaskConical size={15} aria-hidden /> Paper trade this plan
      </Button>
      {open.isError && <span className="text-xs text-critical">{open.error.message}</span>}
    </span>
  );
}

const SECTIONS: [keyof TradePlanReport["content"]["draft"], string][] = [
  ["setup", "Setup"],
  ["timing", "Timing: entry zone, trigger, invalidation"],
  ["scenarios", "Scenarios"],
  ["risk", "Risk and size"],
  ["invalidation", "What invalidates it"],
  ["evidence", "Supporting evidence"],
  ["assumptions", "Assumptions"],
];

export function TradePlanView({ report }: { report: TradePlanReport }) {
  const c = report.content;
  const { card, draft } = c;
  const evidence = useMemo(() => new Map(c.evidence.map((e) => [e.id, e])), [c.evidence]);
  const cited = useMemo(
    () => new Set([draft.headline, ...SECTIONS.flatMap(([k]) => draft[k] as typeof draft.setup)].flatMap((cl) => cl.evidence_ids)),
    [draft],
  );
  const v = c.verification;
  const size = card.size;
  const sc = card.scenarios;

  return (
    <div className="space-y-5">
      <ApprovalBar
        report={report}
        hint="The verifier passed this trade plan. Approve it to allow paper trading (simulated money; nothing is ever sent to an exchange), or reject it."
      />

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <SetupBadge kind={card.setup.kind} status={card.setup.status} />
              <RiskBadge level={card.risk.level} />
              <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs text-ink-2">Paper trading only</span>
            </div>
            <p className="flex gap-2 text-base leading-relaxed text-ink">
              <Target size={18} className="mt-1 shrink-0 text-accent" aria-hidden />
              {draft.headline.text}
            </p>
            <div className="mt-2 text-xs text-muted">
              Trade plan · generated {relativeTime(c.generated_at)} · writer: {draft.writer} · pipeline {c.pipeline_version} ·{" "}
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
            <PaperTradeButton report={report} />
          </div>
        </div>
      </Card>

      <div className="grid gap-5 xl:grid-cols-3">
        <Card title="Setup and levels" className="xl:col-span-2">
          <p className="text-sm text-ink-2">
            Trigger: <span className="text-ink">{card.setup.trigger_text}</span>. These are conditions to watch, not a prediction of when or whether
            price gets there.
          </p>
          <Ladder card={card} />
          <dl className="mt-3 grid gap-x-8 sm:grid-cols-2">
            <div>
              <Row k="Entry zone" v={`${usd(card.timing.entry_zone[0])} – ${usd(card.timing.entry_zone[1])}`} strong />
              <Row k="Trigger level" v={usd(card.timing.trigger_level)} />
              <Row k="Invalidation" v={usd(card.timing.invalidation)} strong />
              <Row k="Profit-taking rule" v={usd(card.timing.profit_level)} />
            </div>
            <div>
              <Row k="Last close" v={usd(card.setup.close)} />
              <Row k="20 / 50-day average" v={`${usd(card.setup.sma20)} / ${usd(card.setup.sma50)}`} />
              <Row k="ATR (14 days)" v={usd(card.setup.atr)} />
              <Row k="Trend filter" v={card.setup.trend_up ? "Up (close and 20-day above the 50-day)" : "Not up"} />
            </div>
          </dl>
        </Card>

        <Card title="Size from max loss">
          <dl>
            <Row k="Paper size" v={`${size.units.toPrecision(4)} ${card.asset.symbol}`} strong />
            <Row k="Notional" v={`${usd(size.notional_usd)} (${size.pct_of_equity.toFixed(1)}% of equity)`} />
            <Row k="Max loss allowed" v={usd(size.max_loss_usd)} />
            <Row k="Loss if stopped" v={usd(size.loss_at_stop_usd)} strong />
            <Row k="Stop distance" v={`${size.stop_distance_pct.toFixed(1)}%`} />
            <Row k="Expected slippage" v={size.expected_slippage_pct === null ? "No order book" : `${size.expected_slippage_pct.toFixed(2)}%`} />
            <Row k="Size limited by" v={label(size.binding)} />
            <Row k="Paper equity" v={usd(size.equity_usd)} />
          </dl>
          <div className="mt-4">
            <div className="mb-1 flex items-baseline justify-between">
              <RiskBadge level={card.risk.level} />
              <span className="text-sm font-semibold tabular">{card.risk.score.toFixed(0)} / 100</span>
            </div>
            <Meter value={card.risk.score} name="Short-term risk score" color="var(--serious)" track="var(--surface-2)" />
          </div>
          {size.warnings.length > 0 && (
            <div className="mt-3">
              <Warnings items={size.warnings} title="Sizing notes" />
            </div>
          )}
        </Card>
      </div>

      <Card
        title={`Scenarios over ${sc.horizon_days} days (historical analogs of this setup)`}
        action={<ReliabilityBadge value={sc.overall.reliability} n={sc.overall.n} />}
      >
        <p className="mb-3 text-xs text-muted">
          Bull, base and bear are defined at ±{sc.band_pct.toFixed(1)}% (half a typical {sc.horizon_days}-day move). Returns include{" "}
          {sc.cost_pct.toFixed(2)}% round-trip costs. Frequencies are what happened before, not probabilities for next time.
        </p>
        <ScenarioTable s={sc} />
        <p className="mt-3 text-xs text-ink-2 tabular">
          All analogs: win rate {sc.overall.win_rate_pct === null ? "—" : `${sc.overall.win_rate_pct.toFixed(0)}%`} ({ci(sc.overall.win_rate_ci)}),
          mean {pct(sc.overall.mean_pct)}
          {sc.overall.mean_ci ? ` (${pct(sc.overall.mean_ci[0])} to ${pct(sc.overall.mean_ci[1])})` : ""}, median {pct(sc.overall.median_pct)}, worst
          drawdown {pct(sc.overall.worst_drawdown_pct)}.
        </p>
      </Card>

      <Card
        title="Backtest (fees and slippage included)"
        action={
          c.backtest_id && (
            <Link to={`/backtests/${c.backtest_id}`} className="flex items-center gap-1 text-xs text-accent">
              <LineChart size={14} aria-hidden /> Open full backtest
            </Link>
          )
        }
      >
        <MetricsTable
          rows={[
            ["In-sample (parameters fitted here)", card.backtest.in_sample],
            ["Out-of-sample", card.backtest.out_of_sample],
            ["Walk-forward", card.backtest.walk_forward],
          ]}
        />
        <div className="mt-3">
          <Warnings items={card.backtest.warnings} title="Overfitting and sample warnings" />
        </div>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        {SECTIONS.map(([key, title]) => (
          <Card key={key} title={title}>
            <ClaimList claims={draft[key] as typeof draft.setup} evidence={evidence} />
          </Card>
        ))}
        <Card title="Skills">
          <div className="space-y-1 text-xs text-ink-2">
            {Object.entries(c.analysts).map(([name, a]) => (
              <div key={name} className="flex justify-between gap-2">
                <span>{label(name)}</span>
                <span className="text-muted">
                  {a.tool_calls} tool calls · {a.claims_source === "llm" ? "model" : "deterministic"} claims
                  {a.stop_reason !== "final" ? ` · ${label(a.stop_reason)}` : ""}
                </span>
              </div>
            ))}
          </div>
          {c.data_gaps.length > 0 && (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-ink-2">
              {c.data_gaps.map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <EvidenceTable items={c.evidence} cited={cited} />
      <p className="rounded-lg border border-line p-3 text-xs text-ink-2">
        <strong className="text-ink">Risk disclaimer.</strong> {c.disclaimer}
      </p>
    </div>
  );
}
