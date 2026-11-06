import { FlaskConical, History, RefreshCw, RotateCcw, X } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router";
import { usePaper, usePaperCancel, usePaperDemoReplay, usePaperReset, usePaperTick, useSession } from "@/api/hooks";
import type { PaperPosition, PaperStatus } from "@/api/types";
import { CompareChart } from "@/components/CompareChart";
import { SetupBadge } from "@/components/TradePlanView";
import { Button, Card, ChangeText, Empty, Spinner, StatTile } from "@/components/ui";
import { pct, usd } from "@/lib/format";
import { ACTIVE_PAPER as ACTIVE } from "@/lib/trading";

const usdFmt = (v: number) => usd(v);

const STATUS_TEXT: Record<PaperStatus, string> = {
  pending: "Waiting for trigger",
  triggered: "Triggered: fills at next open",
  open: "Open",
  closed: "Closed",
  cancelled: "Cancelled",
};

function Origin({ p }: { p: PaperPosition }) {
  return p.origin === "demo_replay" ? (
    <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-2" title="Synthetic history replayed in demo mode">
      Demo replay
    </span>
  ) : p.report_id ? (
    <Link to={`/reports/${p.report_id}`} className="text-xs text-accent">
      Plan
    </Link>
  ) : (
    <span className="text-xs text-muted">Plan</span>
  );
}

function Positions({ rows, active }: { rows: PaperPosition[]; active: boolean }) {
  const cancel = usePaperCancel();
  if (!rows.length) {
    return <Empty>{active ? "No active paper positions. Approve a trade plan and choose “Paper trade this plan”." : "No closed paper trades yet."}</Empty>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="pb-2 font-normal">Coin</th>
            <th className="pb-2 font-normal">Setup</th>
            <th className="pb-2 font-normal">Status</th>
            <th className="pb-2 text-right font-normal">Units</th>
            <th className="pb-2 text-right font-normal">Zone / stop</th>
            <th className="pb-2 text-right font-normal">Entry → {active ? "mark" : "exit"}</th>
            <th className="pb-2 text-right font-normal">{active ? "Unrealised" : "P&L after fees"}</th>
            <th className="pb-2 text-right font-normal">Origin</th>
            {active && <th className="pb-2" />}
          </tr>
        </thead>
        <tbody className="tabular">
          {rows.map((p) => (
            <tr key={p.id} className="border-t border-line align-top">
              <td className="py-2 font-medium">{p.asset?.symbol ?? "?"}</td>
              <td className="py-2">
                <SetupBadge kind={p.setup_kind} />
              </td>
              <td className="py-2 text-xs text-ink-2">
                {STATUS_TEXT[p.status]}
                {p.exit_reason && <div className="text-muted">{p.exit_reason.replace("_", " ")}</div>}
                <div className="text-muted">
                  {p.bars_seen} bars seen{p.bars_held ? ` · held ${p.bars_held}` : ""}
                </div>
              </td>
              <td className="py-2 text-right">{p.units.toPrecision(4)}</td>
              <td className="py-2 text-right text-xs text-ink-2">
                {usd(p.entry_low)}–{usd(p.entry_high)}
                <div>stop {usd(p.stop)}</div>
              </td>
              <td className="py-2 text-right text-xs">
                {p.entry_price ? usd(p.entry_price) : "—"} → {active ? usd(p.mark_price) : p.exit_price ? usd(p.exit_price) : "—"}
              </td>
              <td className="py-2 text-right">
                {active ? (
                  p.unrealised_usd === null ? (
                    <span className="text-muted">—</span>
                  ) : (
                    <span className={p.unrealised_usd >= 0 ? "text-good-text" : "text-critical"}>{usd(p.unrealised_usd)}</span>
                  )
                ) : p.pnl_usd === null ? (
                  <span className="text-muted">—</span>
                ) : (
                  <span className={p.pnl_usd >= 0 ? "text-good-text" : "text-critical"}>{usd(p.pnl_usd)}</span>
                )}
                {p.fees_usd > 0 && <div className="text-[11px] text-muted">fees {usd(p.fees_usd)}</div>}
              </td>
              <td className="py-2 text-right">
                <Origin p={p} />
              </td>
              {active && (
                <td className="py-2 text-right">
                  {p.status !== "open" && (
                    <button
                      type="button"
                      onClick={() => cancel.mutate(p.id)}
                      className="rounded p-1 text-muted hover:bg-surface-2 hover:text-ink"
                      aria-label={`Cancel ${p.asset?.symbol ?? ""} paper position`}
                    >
                      <X size={14} />
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PaperPage({ theme }: { theme: string }) {
  const paper = usePaper();
  const session = useSession();
  const tick = usePaperTick();
  const reset = usePaperReset();
  const replay = usePaperDemoReplay();
  const d = paper.data;
  const series = useMemo(() => {
    if (!d) return [];
    const out = [{ label: "Paper equity", color: "--series-1", points: d.equity.map((p) => ({ date: p.date, value: p.equity })) }];
    if (d.benchmark?.points.length) {
      out.push({ label: d.benchmark.label, color: "--series-2", points: d.benchmark.points.map((p) => ({ date: p.date, value: p.value })) });
    }
    return out;
  }, [d]);

  if (paper.isLoading) return <Spinner />;
  if (!d) return <Empty>Could not load the paper portfolio. {paper.error?.message}</Empty>;
  const active = d.positions.filter((p) => ACTIVE.includes(p.status));
  const done = d.positions.filter((p) => !ACTIVE.includes(p.status));
  const busy = tick.isPending || reset.isPending || replay.isPending;
  const error = tick.error ?? reset.error ?? replay.error;

  return (
    <div className="space-y-5">
      <Card
        title={
          <span className="flex items-center gap-2">
            <FlaskConical size={16} aria-hidden /> Paper portfolio
          </span>
        }
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" onClick={() => tick.mutate(undefined)} disabled={busy} title="Apply every completed daily bar since the last update">
              <RefreshCw size={15} aria-hidden /> Process new bars
            </Button>
            {session.data?.demo && (
              <Button variant="ghost" onClick={() => replay.mutate(undefined)} disabled={busy} title="Restart 75 days in the past on synthetic data">
                <History size={15} aria-hidden /> Demo replay
              </Button>
            )}
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => {
                if (window.confirm("Reset the paper account? Positions and the equity history are cleared.")) reset.mutate(undefined);
              }}
            >
              <RotateCcw size={15} aria-hidden /> Reset
            </Button>
          </div>
        }
      >
        <p className="text-sm text-ink-2">
          Simulated money only. Positions follow the same rules as the backtester on completed daily bars: a close above the trigger arms the
          entry, it fills at the next open (cancelled if it gaps more than 2% above the zone), then exits at the stop, the profit-taking rule or
          the time limit. Lodestar never places orders and holds no exchange keys.
        </p>
        {error && <p className="mt-2 text-sm text-critical">{error.message}</p>}
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        <StatTile label="Paper equity" value={usd(d.equity_usd)} hint={`started ${usd(d.account.starting_cash)} on ${d.account.started_on}`} />
        <StatTile label="Return" value={pct(d.return_pct)} hint={d.benchmark?.return_pct != null ? `Bitcoin ${pct(d.benchmark.return_pct)}` : undefined} />
        <StatTile label="Realised P&L" value={usd(d.realised_pnl_usd)} hint={`${d.closed_trades} closed trades`} />
        <StatTile label="Win rate" value={d.win_rate_pct === null ? "—" : `${d.win_rate_pct.toFixed(0)}%`} hint={d.closed_trades < 10 ? "too few trades to judge" : undefined} />
        <StatTile label="Max drawdown" value={pct(d.max_drawdown_pct)} />
        <StatTile label="Cash" value={usd(d.account.cash)} hint={`open value ${usd(d.open_value_usd)}`} />
      </div>

      <Card
        title="Running performance vs Bitcoin buy-and-hold"
        action={d.account.last_processed && <span className="text-xs text-muted">bars processed to {d.account.last_processed}</span>}
      >
        {d.equity.length > 1 ? (
          <CompareChart series={series} format={usdFmt} theme={theme} baseline={d.account.starting_cash} label="Paper equity versus Bitcoin" />
        ) : (
          <Empty>
            The equity curve starts after the first completed daily bar.{" "}
            {session.data?.demo ? "In demo mode, “Demo replay” fills it with 75 days of synthetic history." : "Check back tomorrow."}
          </Empty>
        )}
      </Card>

      <Card title={`Active (${active.length})`}>
        <Positions rows={active} active />
      </Card>
      <Card
        title={`History (${done.length})`}
        action={done.length > 0 && <span className="text-xs text-ink-2">Realised <ChangeText value={d.realised_pnl_usd / d.account.starting_cash * 100} /></span>}
      >
        <Positions rows={done} active={false} />
      </Card>
    </div>
  );
}
