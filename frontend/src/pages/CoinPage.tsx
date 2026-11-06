import { Sparkles, Star, Target, Workflow } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useAssetReport, useChart, useRuns, useStartRun, useStartTradePlan, useToggleWatch, useWatchlist } from "@/api/hooks";
import { CandleChart } from "@/components/CandleChart";
import { ReportView } from "@/components/ReportView";
import { Button, Card, ChangeText, Empty, Spinner, StatTile, StatusBadge } from "@/components/ui";
import { relativeTime, usd } from "@/lib/format";

const RANGES = [30, 90, 180, 365] as const;

export function CoinPage({ theme }: { theme: string }) {
  const { assetId = "" } = useParams();
  const [days, setDays] = useState<(typeof RANGES)[number]>(90);
  const navigate = useNavigate();
  const chart = useChart(assetId, days);
  const report = useAssetReport(assetId);
  const runs = useRuns(assetId);
  const watchlist = useWatchlist();
  const toggleWatch = useToggleWatch();
  const startRun = useStartRun(assetId);
  const startPlan = useStartTradePlan();

  if (chart.isLoading) return <Spinner />;
  if (!chart.data) return <Empty>Market data unavailable. {chart.error?.message}</Empty>;
  const { asset, snapshot: s } = chart.data;
  const watched = watchlist.data?.some((a) => a.id === asset.id) ?? false;
  const activeRun = runs.data?.find((r) => r.status === "queued" || r.status === "running");

  const run = async () => {
    const { run: r } = await startRun.mutateAsync(Boolean(report.data));
    navigate(`/pipeline/${r.id}`);
  };
  const plan = async () => {
    const { run: r } = await startPlan.mutateAsync({ coingecko_id: asset.coingecko_id });
    navigate(`/pipeline/${r.id}`);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-sm text-ink-2">
            {asset.name} · {asset.symbol} {s.market_cap_rank && <span className="text-muted">· Rank #{s.market_cap_rank}</span>}
          </div>
          <div className="flex items-baseline gap-3">
            <span className="text-5xl font-semibold tracking-tight tabular">{usd(s.price_usd)}</span>
            <ChangeText value={s.change_24h_pct} /> <span className="text-xs text-muted">24h</span>
          </div>
          <div className="mt-1 text-xs text-muted">Updated {relativeTime(s.as_of)}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" onClick={() => toggleWatch.mutate({ assetId: asset.id, watch: !watched })}>
            <Star size={16} fill={watched ? "currentColor" : "none"} aria-hidden /> {watched ? "Watching" : "Watch"}
          </Button>
          {activeRun ? (
            <Link to={`/pipeline/${activeRun.id}`}>
              <Button variant="ghost">
                <Workflow size={16} aria-hidden /> Run in progress
              </Button>
            </Link>
          ) : (
            <>
              <Button variant="ghost" onClick={() => void plan()} disabled={startPlan.isPending} title="Paper-trading plan: entry zone, trigger, invalidation, size, scenarios and a backtest">
                <Target size={16} aria-hidden /> Build trade plan
              </Button>
              <Button onClick={() => void run()} disabled={startRun.isPending}>
                <Sparkles size={16} aria-hidden /> {report.data ? "Re-run analysis" : "Run analysis"}
              </Button>
            </>
          )}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Market cap" value={usd(s.market_cap_usd, { compact: true })} hint={`FDV ${usd(s.fdv_usd, { compact: true })}`} />
        <StatTile label="24h volume" value={usd(s.volume_24h_usd, { compact: true })} />
        <StatTile label="7-day change" value={s.change_7d_pct === null ? "—" : `${s.change_7d_pct.toFixed(2)}%`} hint={`30d ${s.change_30d_pct?.toFixed(1) ?? "—"}% · 1y ${s.change_1y_pct?.toFixed(1) ?? "—"}%`} />
        <StatTile label="From all-time high" value={s.ath_change_pct === null ? "—" : `${s.ath_change_pct.toFixed(1)}%`} hint={`ATH ${usd(s.ath_usd)}`} />
      </div>

      <Card
        title="Price"
        action={
          <div className="flex gap-1" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                aria-pressed={days === r}
                onClick={() => setDays(r)}
                className={`rounded-md px-2.5 py-1 text-xs ${days === r ? "bg-surface-2 font-semibold text-ink" : "text-ink-2 hover:bg-surface-2"}`}
              >
                {r === 365 ? "1Y" : `${r}D`}
              </button>
            ))}
          </div>
        }
      >
        <div className={chart.isFetching ? "opacity-60 transition-opacity" : ""}>
          <CandleChart chart={chart.data} theme={theme} />
        </div>
      </Card>

      {report.isLoading ? (
        <Spinner label="Loading report" />
      ) : report.data ? (
        <ReportView report={report.data} />
      ) : (
        <Empty>
          No verified report yet. Run the analysis to get separate short- and long-term assessments with risk levels, every claim
          tied to evidence.
        </Empty>
      )}

      {runs.data && runs.data.length > 0 && (
        <Card title="Run history">
          <ul className="divide-y divide-line">
            {runs.data.slice(0, 8).map((r) => (
              <li key={r.id} className="flex items-center gap-3 py-2 text-sm">
                <Link to={`/pipeline/${r.id}`} className="hover:text-accent">{relativeTime(r.created_at)}</Link>
                <StatusBadge status={r.status} />
                <span className="text-xs text-muted">{r.kind.replace("_", "-")}{r.error ? ` · ${r.error}` : ""}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
