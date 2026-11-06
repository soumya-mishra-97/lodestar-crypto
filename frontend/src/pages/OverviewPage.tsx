import { Link } from "react-router";
import { useOverview } from "@/api/hooks";
import type { PortfolioRisk } from "@/api/types";
import { AllocationBar, Sparkline } from "@/components/AllocationBar";
import { Card, ChangeText, Empty, Meter, RiskBadge, Spinner, StanceBadge, StatTile, StatusBadge } from "@/components/ui";
import { relativeTime, usd } from "@/lib/format";

function RiskTile({ title, risk }: { title: string; risk: PortfolioRisk | null }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="flex items-center justify-between text-xs text-ink-2">
        {title} {risk && <RiskBadge level={risk.level} />}
      </div>
      {risk ? (
        <>
          <div className="mt-1 text-2xl font-semibold">
            {risk.score.toFixed(0)}
            <span className="text-xs font-normal text-muted"> / 100</span>
          </div>
          <Meter value={risk.score} name={title} color="var(--serious)" track="var(--surface-2)" />
          <div className="mt-1 text-xs text-muted">
            Concentration +{risk.concentration_points} · largest position {risk.largest_weight_pct.toFixed(0)}%
            {risk.volatility_30d_pct !== null && ` · 30d vol ${risk.volatility_30d_pct.toFixed(0)}%`}
          </div>
        </>
      ) : (
        <div className="mt-1 text-sm text-muted">Add holdings to see portfolio risk</div>
      )}
    </div>
  );
}

export function OverviewPage() {
  const { data, isLoading, error } = useOverview();
  if (isLoading) return <Spinner />;
  if (error || !data) return <Empty>Could not load the overview. {error?.message}</Empty>;
  const p = data.portfolio;
  const fg = data.market_sentiment;
  const latest = data.latest_report;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-sm text-ink-2">Portfolio value</div>
          <div className="text-5xl font-semibold tracking-tight tabular">{usd(p.total_value_usd)}</div>
          <div className="mt-1 text-sm">
            <ChangeText value={p.change_24h_pct} /> <span className="text-xs text-muted">24h · {p.positions} positions</span>
            {p.stale_prices > 0 && <span className="ml-2 text-xs text-critical">{p.stale_prices} price(s) unavailable</span>}
          </div>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Unrealised P&L" value={usd(p.total_pnl_usd)} delta={p.total_pnl_pct} deltaLabel="vs cost basis" />
        <RiskTile title="Long-term portfolio risk" risk={data.risk.long_term} />
        <RiskTile title="Short-term portfolio risk" risk={data.risk.short_term} />
        <StatTile
          label="Market sentiment"
          value={fg ? `${fg.fear_greed_value} · ${fg.classification}` : "—"}
          hint="Crypto Fear & Greed Index (0-100)"
        />
      </div>
      <p className="-mt-3 text-xs text-muted">
        Portfolio risk blends each position's risk score (from its latest report, or computed from price history) by value, plus a
        concentration charge.
      </p>

      <div className="grid gap-5 lg:grid-cols-5">
        <Card title="Allocation" className="lg:col-span-3" action={<Link to="/portfolio" className="text-xs text-accent">Manage</Link>}>
          {data.allocation.length ? (
            <AllocationBar slices={data.allocation} />
          ) : (
            <Empty>No holdings yet. Add them manually, from a CSV or from a public address on the Portfolio page.</Empty>
          )}
        </Card>
        <Card title="Latest report" className="lg:col-span-2" action={latest && <StatusBadge status={latest.status} />}>
          {latest ? (
            <div className="space-y-3">
              <Link to={`/reports/${latest.id}`} className="block text-sm leading-relaxed text-ink hover:text-accent">
                {latest.headline}
              </Link>
              <div className="flex flex-wrap gap-2 text-xs text-ink-2">
                <span>Short</span> <StanceBadge stance={latest.short_term_stance} /> <RiskBadge level={latest.short_term_risk} />
              </div>
              <div className="flex flex-wrap gap-2 text-xs text-ink-2">
                <span>Long</span> <StanceBadge stance={latest.long_term_stance} /> <RiskBadge level={latest.long_term_risk} />
              </div>
              <div className="text-xs text-muted">{relativeTime(latest.created_at)}</div>
            </div>
          ) : (
            <Empty>No reports yet. Add a coin with the search box to start a pipeline run.</Empty>
          )}
        </Card>
      </div>

      <Card title="Watchlist">
        {data.watchlist.length === 0 ? (
          <Empty>Search for a coin above (try “Polygon”) to add it and run the analysis pipeline.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th className="pb-2 font-normal">Asset</th>
                  <th className="pb-2 text-right font-normal">Price</th>
                  <th className="pb-2 text-right font-normal">24h</th>
                  <th className="pb-2 text-right font-normal">7d</th>
                  <th className="pb-2 pl-4 font-normal">30 days</th>
                  <th className="pb-2 font-normal">Short term</th>
                  <th className="pb-2 font-normal">Long term</th>
                  <th className="pb-2 font-normal">Report</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {data.watchlist.map(({ asset, snapshot, sparkline, latest_report: r }) => (
                  <tr key={asset.id} className="border-t border-line hover:bg-surface-2">
                    <td className="py-2.5">
                      <Link to={`/coins/${asset.id}`} className="font-medium text-ink hover:text-accent">
                        {asset.name} <span className="text-xs text-muted">{asset.symbol}</span>
                      </Link>
                    </td>
                    <td className="py-2.5 text-right">{usd(snapshot?.price_usd)}</td>
                    <td className="py-2.5 text-right"><ChangeText value={snapshot?.change_24h_pct} /></td>
                    <td className="py-2.5 text-right"><ChangeText value={snapshot?.change_7d_pct} /></td>
                    <td className="py-2.5 pl-4"><Sparkline values={sparkline} label={asset.symbol} /></td>
                    <td className="py-2.5">
                      {r ? <span className="flex gap-1"><StanceBadge stance={r.short_term_stance} /><RiskBadge level={r.short_term_risk} /></span> : "—"}
                    </td>
                    <td className="py-2.5">
                      {r ? <span className="flex gap-1"><StanceBadge stance={r.long_term_stance} /><RiskBadge level={r.long_term_risk} /></span> : "—"}
                    </td>
                    <td className="py-2.5 text-xs">
                      {r ? <Link to={`/reports/${r.id}`}><StatusBadge status={r.status} /></Link> : <span className="text-muted">none</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Recent pipeline runs" action={<Link to="/pipeline" className="text-xs text-accent">All runs</Link>}>
        {data.recent_runs.length === 0 ? (
          <Empty>No runs yet.</Empty>
        ) : (
          <ul className="divide-y divide-line">
            {data.recent_runs.map((run) => (
              <li key={run.id} className="flex items-center gap-3 py-2 text-sm">
                <Link to={`/pipeline/${run.id}`} className="font-medium hover:text-accent">{run.asset?.symbol ?? "?"}</Link>
                <StatusBadge status={run.status} />
                <span className="text-xs text-muted">{run.kind.replace("_", "-")} · {run.llm_mode}</span>
                <span className="ml-auto text-xs text-muted">{relativeTime(run.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
