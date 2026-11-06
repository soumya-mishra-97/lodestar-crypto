import { CheckCircle2, MinusCircle, Play, Radar, Star } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useLatestScan, useStartScan, useStartTradePlan } from "@/api/hooks";
import type { ScanRow } from "@/api/types";
import { SetupBadge } from "@/components/TradePlanView";
import { Button, Card, Empty, inputClass, Meter, Spinner, StatusBadge } from "@/components/ui";
import { pct, relativeTime, usd } from "@/lib/format";

const SIZES = [10, 20, 30, 50];

function Liquidity({ ok }: { ok: boolean }) {
  return ok ? (
    <span className="inline-flex items-center gap-1 text-xs text-ink-2">
      <CheckCircle2 size={13} style={{ color: "var(--good)" }} aria-hidden /> Liquid
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-xs text-muted">
      <MinusCircle size={13} aria-hidden /> Thin
    </span>
  );
}

function PlanButton({ row }: { row: ScanRow }) {
  const start = useStartTradePlan();
  const navigate = useNavigate();
  return (
    <Button
      variant={row.shortlisted ? "primary" : "ghost"}
      className="px-2 py-1 text-xs"
      disabled={start.isPending || !row.metrics}
      title={start.error?.message}
      onClick={() =>
        start.mutate({ coingecko_id: row.coingecko_id }, { onSuccess: (r) => void navigate(`/pipeline/${r.run.id}`) })
      }
    >
      {start.isPending ? "Starting…" : "Build trade plan"}
    </Button>
  );
}

function ScanTable({ rows }: { rows: ScanRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="pb-2 font-normal">#</th>
            <th className="pb-2 font-normal">Coin</th>
            <th className="w-40 pb-2 font-normal">Score</th>
            <th className="pb-2 text-right font-normal" title="Close above 20 and 50-day averages, 20 above 50, 20-day rising">
              Trend
            </th>
            <th className="pb-2 text-right font-normal" title="Distance from the prior 20-day high">
              vs 20d high
            </th>
            <th className="pb-2 text-right font-normal" title="7-day vs 30-day average volume">
              Volume
            </th>
            <th className="pb-2 text-right font-normal" title="30-day return minus Bitcoin's">
              vs BTC (30d)
            </th>
            <th className="pb-2 text-right font-normal">24h volume</th>
            <th className="pb-2 pl-4 font-normal">Setup</th>
            <th className="pb-2 font-normal" />
          </tr>
        </thead>
        <tbody className="tabular">
          {rows.map((r) => {
            const m = r.metrics;
            return (
              <tr key={r.coingecko_id} className="border-t border-line align-middle">
                <td className="py-2 text-muted">{r.rank}</td>
                <td className="py-2">
                  <div className="flex items-center gap-1.5">
                    {r.shortlisted && <Star size={13} style={{ color: "var(--warning)" }} aria-label="Shortlisted" />}
                    {r.asset_id ? (
                      <Link to={`/coins/${r.asset_id}`} className="font-medium hover:text-accent">
                        {r.symbol}
                      </Link>
                    ) : (
                      <span className="font-medium">{r.symbol}</span>
                    )}
                    <span className="hidden text-xs text-muted lg:inline">{r.name}</span>
                  </div>
                  <Liquidity ok={r.passes_liquidity} />
                </td>
                <td className="py-2">
                  {r.score === null ? (
                    <span className="text-xs text-critical" title={r.error ?? ""}>
                      No data
                    </span>
                  ) : (
                    <div className="flex items-center gap-2">
                      <span className="w-9 text-ink">{r.score.toFixed(0)}</span>
                      <Meter value={r.score} name={`${r.symbol} scanner score`} track="var(--surface-2)" />
                    </div>
                  )}
                </td>
                <td className="py-2 text-right">{m ? `${m.trend_points}/4` : "—"}</td>
                <td className="py-2 text-right">{m ? (m.breakout ? "Breakout" : pct(m.breakout_distance_pct)) : "—"}</td>
                <td className="py-2 text-right">{m ? `${m.volume_ratio.toFixed(2)}×` : "—"}</td>
                <td className="py-2 text-right">{m ? pct(m.rs_vs_btc_pct) : "—"}</td>
                <td className="py-2 text-right text-ink-2">{usd(m?.volume_24h_usd, { compact: true })}</td>
                <td className="py-2 pl-4">{m && <SetupBadge kind={m.setup_kind} />}</td>
                <td className="py-2 text-right">
                  <PlanButton row={r} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ScannerPage() {
  const scan = useLatestScan();
  const start = useStartScan();
  const [universe, setUniverse] = useState<"top" | "watchlist">("top");
  const [topN, setTopN] = useState(20);
  const s = scan.data;
  const running = s?.status === "running";

  return (
    <div className="space-y-5">
      <Card
        title={
          <span className="flex items-center gap-2">
            <Radar size={16} aria-hidden /> Market scanner
          </span>
        }
        action={s && <span className="text-xs text-muted">Last scan {relativeTime(s.created_at)} · {s.data_mode} data</span>}
      >
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            <span className="mb-1 block text-xs text-ink-2">Universe</span>
            <select className={inputClass} value={universe} onChange={(e) => setUniverse(e.target.value as "top" | "watchlist")}>
              <option value="top">Top coins by market cap</option>
              <option value="watchlist">My watchlist</option>
            </select>
          </label>
          {universe === "top" && (
            <label className="text-sm">
              <span className="mb-1 block text-xs text-ink-2">How many</span>
              <select className={inputClass} value={topN} onChange={(e) => setTopN(Number(e.target.value))}>
                {SIZES.map((n) => (
                  <option key={n} value={n}>
                    Top {n}
                  </option>
                ))}
              </select>
            </label>
          )}
          <Button
            onClick={() => start.mutate(universe === "top" ? { universe, top_n: topN } : { universe })}
            disabled={start.isPending || running}
          >
            <Play size={15} aria-hidden /> {running ? "Scanning…" : "Run scan"}
          </Button>
          {start.isError && <span className="text-sm text-critical">{start.error.message}</span>}
        </div>
        <p className="mt-3 text-xs text-muted">
          Each coin is scored 0–100 in code: trend (40), breakout (20), volume spike (20) and strength against Bitcoin (20). Coins below the
          24-hour volume floor are ranked last. Scanning many charts always turns up something that looks like an edge, so the score is a
          reason to look closer, not a signal. Selecting a coin runs the full pipeline with statistics, sizing and a backtest.
        </p>
      </Card>

      {scan.isLoading ? (
        <Spinner />
      ) : !s ? (
        <Empty>No scans yet. Run one to rank the most liquid coins.</Empty>
      ) : (
        <Card
          title={`Ranked shortlist · ${s.universe === "top" ? `top ${s.top_n}` : "watchlist"}`}
          action={<StatusBadge status={s.status === "running" ? "running" : s.status} />}
        >
          {running && (
            <div className="mb-4">
              <div className="mb-1 flex justify-between text-xs text-ink-2">
                <span>Scoring coins</span>
                <span className="tabular">
                  {s.progress} / {s.total || "…"}
                </span>
              </div>
              <Meter value={s.progress} max={Math.max(1, s.total)} name="Scan progress" />
            </div>
          )}
          {s.status === "failed" && <p className="text-sm text-critical">Scan failed: {s.error}</p>}
          {s.results && s.results.length > 0 && (
            <>
              <p className="mb-3 text-xs text-ink-2">
                <Star size={12} className="inline" style={{ color: "var(--warning)" }} aria-hidden /> marks the shortlist: the top{" "}
                {s.results.filter((r) => r.shortlisted).length} liquid coins by score.
              </p>
              <ScanTable rows={s.results} />
            </>
          )}
        </Card>
      )}
    </div>
  );
}
