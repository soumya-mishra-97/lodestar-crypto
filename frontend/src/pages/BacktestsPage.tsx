import { FlaskConical, Play } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useAssets, useBacktest, useBacktests, useRunBacktest } from "@/api/hooks";
import type { BacktestResult, SetupKind } from "@/api/types";
import { CompareChart } from "@/components/CompareChart";
import { MetricsTable, SetupBadge, Warnings } from "@/components/TradePlanView";
import { Button, Card, ChangeText, Empty, inputClass, Spinner, StatTile } from "@/components/ui";
import { pct, relativeTime, usd } from "@/lib/format";
import { SETUP_LABEL } from "@/lib/trading";

const indexFmt = (v: number) => v.toFixed(1);

function RunForm() {
  const assets = useAssets();
  const runBacktest = useRunBacktest();
  const navigate = useNavigate();
  const [coin, setCoin] = useState("");
  const [setup, setSetup] = useState<SetupKind | "auto">("auto");
  const selected = coin || assets.data?.[0]?.coingecko_id || "";
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="text-sm">
        <span className="mb-1 block text-xs text-ink-2">Coin</span>
        <select className={inputClass} value={selected} onChange={(e) => setCoin(e.target.value)}>
          {(assets.data ?? []).map((a) => (
            <option key={a.id} value={a.coingecko_id}>
              {a.symbol} · {a.name}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        <span className="mb-1 block text-xs text-ink-2">Setup</span>
        <select className={inputClass} value={setup} onChange={(e) => setSetup(e.target.value as SetupKind | "auto")}>
          <option value="auto">The setup tracked today</option>
          {(Object.keys(SETUP_LABEL) as SetupKind[]).map((k) => (
            <option key={k} value={k}>
              {SETUP_LABEL[k]}
            </option>
          ))}
        </select>
      </label>
      <Button
        disabled={!selected || runBacktest.isPending}
        onClick={() =>
          runBacktest.mutate(
            { coingecko_id: selected, ...(setup === "auto" ? {} : { setup }) },
            { onSuccess: (r) => void navigate(`/backtests/${r.id}`) },
          )
        }
      >
        <Play size={15} aria-hidden /> {runBacktest.isPending ? "Running…" : "Run backtest"}
      </Button>
      {runBacktest.isError && <span className="text-sm text-critical">{runBacktest.error.message}</span>}
    </div>
  );
}

export function BacktestsPage() {
  const backtests = useBacktests();
  return (
    <div className="space-y-5">
      <Card
        title={
          <span className="flex items-center gap-2">
            <FlaskConical size={16} aria-hidden /> Backtests
          </span>
        }
      >
        <RunForm />
        <p className="mt-3 text-xs text-muted">
          Signals use the daily close; fills happen at the next open with fees and slippage on both sides. Parameters are fitted on the first
          70% of history and judged on the rest (out-of-sample), plus rolling walk-forward folds. Every trade-plan run saves its backtest here.
        </p>
      </Card>
      <Card title="History">
        {backtests.isLoading ? (
          <Spinner />
        ) : !backtests.data?.length ? (
          <Empty>No backtests yet. Run one above, or build a trade plan from the scanner.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th className="pb-2 font-normal">Coin</th>
                  <th className="pb-2 font-normal">Setup</th>
                  <th className="pb-2 text-right font-normal">OOS trades</th>
                  <th className="pb-2 text-right font-normal">OOS return</th>
                  <th className="pb-2 text-right font-normal">Buy and hold</th>
                  <th className="pb-2 text-right font-normal">Sharpe</th>
                  <th className="pb-2 text-right font-normal">Warnings</th>
                  <th className="pb-2 text-right font-normal">Source</th>
                  <th className="pb-2 text-right font-normal">When</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {backtests.data.map((b) => (
                  <tr key={b.id} className="border-t border-line">
                    <td className="py-2">
                      <Link to={`/backtests/${b.id}`} className="font-medium hover:text-accent">
                        {b.asset?.symbol ?? b.summary.symbol}
                      </Link>
                    </td>
                    <td className="py-2">
                      <SetupBadge kind={b.kind} />
                    </td>
                    <td className="py-2 text-right">{b.summary.oos_trades}</td>
                    <td className="py-2 text-right">
                      <ChangeText value={b.summary.oos_total_return_pct} />
                    </td>
                    <td className="py-2 text-right text-ink-2">{pct(b.summary.oos_buy_hold_pct)}</td>
                    <td className="py-2 text-right">{b.summary.oos_sharpe.toFixed(2)}</td>
                    <td className="py-2 text-right">{b.summary.warnings || "—"}</td>
                    <td className="py-2 text-right text-xs text-muted">{b.run_id ? "Trade plan" : "Manual"}</td>
                    <td className="py-2 text-right text-xs text-muted">{relativeTime(b.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function Detail({ r, theme }: { r: BacktestResult; theme: string }) {
  const series = useMemo(
    () => [
      { label: "Strategy (out-of-sample, after costs)", color: "--series-1", points: r.equity.map((p) => ({ date: p.date, value: p.strategy })) },
      { label: "Buy and hold", color: "--series-2", points: r.equity.map((p) => ({ date: p.date, value: p.buy_hold })), dashed: true },
    ],
    [r.equity],
  );
  const o = r.out_of_sample;
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <StatTile label="Out-of-sample return" value={pct(o.total_return_pct)} hint={`Buy and hold ${pct(o.buy_hold_return_pct)}`} />
        <StatTile label="Trades (out-of-sample)" value={String(o.trades)} hint={`over ${o.days} days`} />
        <StatTile label="Win rate" value={o.win_rate_pct === null ? "—" : `${o.win_rate_pct.toFixed(0)}%`} />
        <StatTile label="Max drawdown" value={pct(o.max_drawdown_pct)} />
        <StatTile label="Sharpe (daily, annualised)" value={o.sharpe.toFixed(2)} hint={`In-sample ${r.in_sample.sharpe.toFixed(2)}`} />
      </div>

      <Warnings items={r.warnings} title="Overfitting and sample warnings" />

      <Card title="Out-of-sample equity vs buy and hold (both indexed to 100)">
        {r.equity.length ? (
          <CompareChart series={series} format={indexFmt} theme={theme} baseline={100} label="Strategy versus buy and hold" />
        ) : (
          <Empty>No out-of-sample period.</Empty>
        )}
      </Card>

      <Card title="Metrics">
        <MetricsTable
          rows={[
            ["In-sample (parameters fitted here)", r.in_sample],
            ["Out-of-sample", r.out_of_sample],
            ["Walk-forward (test folds only)", r.walk_forward],
          ]}
        />
        <p className="mt-2 text-xs text-muted">
          Chosen parameters: {r.chosen_params.lookback}-day lookback, stop at {r.chosen_params.atr_mult}× ATR, profit rule at{" "}
          {r.chosen_params.reward_r}R. Median Sharpe across the {r.config.lookbacks.length * r.config.atr_mults.length}-combination grid:{" "}
          {r.grid_median_sharpe.toFixed(2)}.
        </p>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card title={`Walk-forward folds (${r.folds.length})`}>
          {r.folds.length ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th className="pb-2 font-normal">Fold</th>
                  <th className="pb-2 font-normal">Params</th>
                  <th className="pb-2 text-right font-normal">Train Sharpe</th>
                  <th className="pb-2 text-right font-normal">Test trades</th>
                  <th className="pb-2 text-right font-normal">Test return</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {r.folds.map((f, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="py-1.5 text-ink-2">{i + 1}</td>
                    <td className="py-1.5 text-xs text-ink-2">
                      {f.params.lookback}d · {f.params.atr_mult}× ATR
                    </td>
                    <td className="py-1.5 text-right">{f.train_metrics.sharpe.toFixed(2)}</td>
                    <td className="py-1.5 text-right">{f.test_metrics.trades}</td>
                    <td className="py-1.5 text-right">
                      <ChangeText value={f.test_metrics.total_return_pct} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>Not enough history for walk-forward folds.</Empty>
          )}
        </Card>
        <Card title={`Out-of-sample trades (${r.oos_trades.length})`}>
          {r.oos_trades.length ? (
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface">
                  <tr className="text-left text-xs text-muted">
                    <th className="pb-2 font-normal">Entry</th>
                    <th className="pb-2 font-normal">Exit</th>
                    <th className="pb-2 text-right font-normal">Price in → out</th>
                    <th className="pb-2 text-right font-normal">Net return</th>
                    <th className="pb-2 pl-3 font-normal">Exit reason</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {r.oos_trades.map((t) => (
                    <tr key={t.entry_date} className="border-t border-line">
                      <td className="py-1.5 text-xs text-ink-2">{t.entry_date}</td>
                      <td className="py-1.5 text-xs text-ink-2">{t.exit_date}</td>
                      <td className="py-1.5 text-right text-xs">
                        {usd(t.entry)} → {usd(t.exit)}
                      </td>
                      <td className="py-1.5 text-right">
                        <ChangeText value={t.return_pct} />
                      </td>
                      <td className="py-1.5 pl-3 text-xs text-ink-2">{t.reason.replace("_", " ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty>No trades in the out-of-sample period.</Empty>
          )}
        </Card>
      </div>

      <Card title="Assumptions">
        <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
          {r.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
          <li>
            {r.bars} daily bars from {r.first_date} to {r.last_date}; {Math.round(r.config.in_sample_fraction * 100)}% in-sample; walk-forward
            trains on {r.config.wf_train} days and tests on the next {r.config.wf_test}; {r.config.horizon}-day time exit.
          </li>
        </ul>
      </Card>
    </>
  );
}

export function BacktestDetailPage({ theme }: { theme: string }) {
  const { backtestId } = useParams();
  const bt = useBacktest(backtestId);
  if (bt.isLoading) return <Spinner />;
  if (!bt.data?.result) return <Empty>Backtest not found. {bt.error?.message}</Empty>;
  const b = bt.data;
  const result = b.result as BacktestResult;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3 text-sm text-ink-2">
        <Link to="/backtests" className="text-accent">
          Backtests
        </Link>
        <span>/</span>
        <span className="font-medium text-ink">{b.asset?.name ?? b.summary.symbol}</span>
        <SetupBadge kind={b.kind} />
        <span className="ml-auto text-xs text-muted">
          {b.summary.data_mode} data · fees {result.config.fee_bps} bps + slippage {result.config.slippage_bps} bps per side ·{" "}
          {relativeTime(b.created_at)}
          {b.run_id && (
            <>
              {" · "}
              <Link to={`/pipeline/${b.run_id}`} className="text-accent">
                from a trade-plan run
              </Link>
            </>
          )}
        </span>
      </div>
      <Detail r={result} theme={theme} />
    </div>
  );
}
