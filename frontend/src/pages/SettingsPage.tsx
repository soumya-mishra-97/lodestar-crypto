import { CheckCircle2, CircleDashed } from "lucide-react";
import { useState } from "react";
import { useSettings, useUpdatePreferences } from "@/api/hooks";
import type { Preferences } from "@/api/types";
import { Button, Card, Empty, inputClass, Spinner } from "@/components/ui";
import { STEP_LABEL } from "@/lib/pipeline";

type NumericPref = Exclude<keyof Preferences, "polymarket_enabled">;

const TRADING_FIELDS: { key: NumericPref; label: string; hint: string; min: number; max: number; step: number }[] = [
  { key: "max_loss_pct", label: "Max loss per trade (% of paper equity)", hint: "Position size is derived from this and the stop distance.", min: 0.1, max: 5, step: 0.1 },
  { key: "max_position_pct", label: "Max position (% of paper equity)", hint: "Concentration cap applied after the max-loss size.", min: 1, max: 100, step: 1 },
  { key: "max_slippage_pct", label: "Max expected slippage (%)", hint: "The order-book walk shrinks the size until slippage fits.", min: 0.05, max: 5, step: 0.05 },
  { key: "fee_bps", label: "Fee per side (bps)", hint: "Used by statistics, the backtester and paper fills.", min: 0, max: 100, step: 1 },
  { key: "slippage_bps", label: "Slippage per side (bps)", hint: "Added to every simulated fill.", min: 0, max: 100, step: 1 },
  { key: "horizon_days", label: "Scenario and time-exit horizon (days)", hint: "Bull/base/bear outcomes are measured over this many days.", min: 3, max: 60, step: 1 },
  { key: "min_volume_usd", label: "Scanner liquidity floor (24h volume, USD)", hint: "Coins below it are ranked last and never shortlisted.", min: 0, max: 1e11, step: 1_000_000 },
  { key: "paper_starting_cash", label: "Paper starting cash (USD)", hint: "Applies the next time the paper account is reset.", min: 100, max: 1e9, step: 100 },
];

function TradingPreferences({ prefs }: { prefs: Preferences }) {
  const update = useUpdatePreferences();
  const [draft, setDraft] = useState<Partial<Record<NumericPref, string>>>({});
  const changed = Object.keys(draft).length > 0;
  const save = () => {
    const body = Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, Number(v)])) as Partial<Preferences>;
    update.mutate(body, { onSuccess: () => setDraft({}) });
  };
  return (
    <Card title="Trading (paper only)" className="lg:col-span-2">
      <div className="grid gap-4 md:grid-cols-2">
        {TRADING_FIELDS.map((f) => (
          <div key={f.key} className="text-sm">
            <label htmlFor={f.key}>{f.label}</label>
            <span className="block text-xs text-muted">{f.hint}</span>
            <input
              id={f.key}
              className={`${inputClass} mt-1 max-w-48`}
              type="number"
              min={f.min}
              max={f.max}
              step={f.step}
              value={draft[f.key] ?? String(prefs[f.key])}
              onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
            />
          </div>
        ))}
      </div>
      <div className="mt-4 flex items-center gap-3">
        <Button variant="ghost" disabled={!changed || update.isPending} onClick={save}>
          Save trading settings
        </Button>
        {update.isError && <span className="text-sm text-critical">{update.error.message}</span>}
      </div>
      <p className="mt-3 text-xs text-muted">
        There is no order placement anywhere in Lodestar and no field for exchange keys with trading rights. These settings only change the
        simulated numbers.
      </p>
    </Card>
  );
}

export function SettingsPage({ theme, onToggleTheme }: { theme: string; onToggleTheme: () => void }) {
  const settings = useSettings();
  const update = useUpdatePreferences();
  const [tolerance, setTolerance] = useState<string | null>(null);
  if (settings.isLoading) return <Spinner />;
  const s = settings.data;
  if (!s) return <Empty>Could not load settings. {settings.error?.message}</Empty>;
  const prefs = s.preferences;

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card title="Data">
        <p className="text-sm text-ink">
          Mode: <strong>{s.demo ? "Demo (synthetic data)" : "Live"}</strong>
        </p>
        <p className="mt-2 text-sm text-ink-2">
          {s.demo
            ? "No market-data key is configured, so every source returns deterministic synthetic data and a banner is shown. Set LS_COINGECKO_API_KEY (a free demo key works) or LS_DATA_MODE=live in .env, then restart."
            : "Live data from CoinGecko, Kraken, DefiLlama, alternative.me, RSS news and (optionally) Polymarket. Prices are reconciled across three sources."}
        </p>
        <table className="mt-4 w-full text-sm">
          <tbody>
            {s.providers.map((p) => (
              <tr key={p.name} className="border-t border-line">
                <td className="py-1.5">
                  <span className="flex items-center gap-2">
                    {p.active ? <CheckCircle2 size={14} style={{ color: "var(--good)" }} aria-label="active" /> : <CircleDashed size={14} className="text-muted" aria-label="inactive" />}
                    {p.name}
                  </span>
                </td>
                <td className="py-1.5 text-xs text-ink-2">{p.role}</td>
                <td className="py-1.5 text-right text-xs text-muted">{p.keyed ? "key set" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="Agents">
        <p className="text-sm text-ink">
          Analysts and writer: <strong>{s.llm.configured ? `${s.llm.model} (effort ${s.llm.effort})` : "Deterministic"}</strong>
        </p>
        <p className="mt-2 text-sm text-ink-2">
          {s.llm.configured
            ? "Claude chooses which read-only tools each analyst calls and writes the report. All numbers are still computed in code, and the verifier checks every claim."
            : "Without ANTHROPIC_API_KEY, analysts follow scripted tool plans and a template writer explains the evidence. The pipeline, verifier and approval gate are identical."}
        </p>
        <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
          <dt className="text-ink-2">Analyst step limit</dt>
          <dd className="text-right tabular">{s.pipeline.max_agent_steps}</dd>
          <dt className="text-ink-2">Repair loops before failing closed</dt>
          <dd className="text-right tabular">{s.pipeline.max_repairs}</dd>
          <dt className="text-ink-2">Human approval</dt>
          <dd className="text-right">Always required</dd>
          <dt className="text-ink-2">Daily reports</dt>
          <dd className="text-right tabular">{String(s.schedule.daily_report_hour_utc).padStart(2, "0")}:00 UTC</dd>
        </dl>
        <p className="mt-3 text-xs text-muted">Pipeline: {s.pipeline.steps.map((x) => STEP_LABEL[x] ?? x).join(" → ")}</p>
      </Card>

      <Card title="Analysis preferences">
        <div className="space-y-4">
          <label className="flex items-center justify-between gap-3 text-sm">
            <span>
              Polymarket odds as sentiment evidence
              <span className="block text-xs text-muted">Crowd odds are context, never a forecast.</span>
            </span>
            <input
              type="checkbox"
              checked={prefs.polymarket_enabled}
              onChange={(e) => update.mutate({ polymarket_enabled: e.target.checked })}
              className="h-4 w-4 accent-[var(--accent)]"
            />
          </label>
          <div className="text-sm">
            <label htmlFor="tolerance">Price mismatch tolerance (%)</label>
            <span className="block text-xs text-muted">Sources deviating from the cross-source median by more than this are flagged.</span>
            <div className="mt-2 flex gap-2">
              <input
                id="tolerance"
                className={`${inputClass} max-w-32`}
                type="number"
                step="0.1"
                min="0.1"
                max="10"
                value={tolerance ?? String(prefs.mismatch_tolerance_pct)}
                onChange={(e) => setTolerance(e.target.value)}
              />
              <Button
                variant="ghost"
                disabled={tolerance === null || update.isPending}
                onClick={() => update.mutate({ mismatch_tolerance_pct: Number(tolerance) }, { onSuccess: () => setTolerance(null) })}
              >
                Save
              </Button>
            </div>
          </div>
          {update.isError && <p className="text-sm text-critical">{update.error.message}</p>}
        </div>
      </Card>

      <TradingPreferences prefs={prefs} />

      <Card title="Display and access">
        <div className="flex items-center justify-between text-sm">
          <span>Theme</span>
          <Button variant="ghost" onClick={onToggleTheme}>{theme === "dark" ? "Switch to light" : "Switch to dark"}</Button>
        </div>
        <p className="mt-4 text-sm text-ink-2">
          Access: <strong className="text-ink">{s.auth_mode === "local" ? "Single-user local mode" : "Password login"}</strong>.{" "}
          {s.auth_mode === "local"
            ? "No login because the stack is bound to localhost. Set LS_AUTH_MODE=password before exposing it anywhere else (production requires it)."
            : "Owner account with short-lived tokens and a rotating HttpOnly refresh cookie."}
        </p>
        <p className="mt-3 text-xs text-muted">Lodestar is read-only: it never holds private keys and never places trades. Trading features are paper only.</p>
      </Card>
    </div>
  );
}
