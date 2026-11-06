import { ShieldAlert, Trash2, Upload } from "lucide-react";
import { type FormEvent, Fragment, useState } from "react";
import { Link } from "react-router";
import { useAssets, useImportAddress, useImportCsv, usePortfolio, useRemoveHolding, useUpsertHolding } from "@/api/hooks";
import type { AddressImportResult, CsvImportResult } from "@/api/types";
import { AllocationBar } from "@/components/AllocationBar";
import { Button, Card, ChangeText, Empty, inputClass, Spinner, StatTile } from "@/components/ui";
import { num, usd } from "@/lib/format";

const CSV_EXAMPLE = "symbol,quantity,avg_cost_usd,notes\nPOL,12000,0.31,cold wallet\nBTC,0.25,61000,\n";

function ManualForm() {
  const assets = useAssets();
  const upsert = useUpsertHolding();
  const [form, setForm] = useState({ assetId: "", quantity: "", cost: "", notes: "" });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    upsert.mutate(
      { asset_id: form.assetId, quantity: Number(form.quantity), avg_cost_usd: form.cost ? Number(form.cost) : null, notes: form.notes || null },
      { onSuccess: () => setForm({ assetId: "", quantity: "", cost: "", notes: "" }) },
    );
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <select className={inputClass} value={form.assetId} onChange={(e) => setForm({ ...form, assetId: e.target.value })} required aria-label="Asset">
        <option value="">Select a tracked coin…</option>
        {assets.data?.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name} ({a.symbol})
          </option>
        ))}
      </select>
      <div className="grid grid-cols-2 gap-3">
        <input className={inputClass} type="number" step="any" min="0" placeholder="Quantity" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} required aria-label="Quantity" />
        <input className={inputClass} type="number" step="any" min="0" placeholder="Avg cost (USD)" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} aria-label="Average cost in USD" />
      </div>
      <input className={inputClass} maxLength={1000} placeholder="Notes (encrypted at rest)" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} aria-label="Notes" />
      <Button type="submit" disabled={upsert.isPending}>Save holding</Button>
      {upsert.isError && <p className="text-sm text-critical">{upsert.error.message}</p>}
      <p className="text-xs text-muted">Not listed? Add the coin with the search box first.</p>
    </form>
  );
}

function CsvForm() {
  const importCsv = useImportCsv();
  const [text, setText] = useState("");
  const [result, setResult] = useState<CsvImportResult | null>(null);
  const onFile = async (file: File | undefined) => {
    if (file) setText(await file.text());
  };
  return (
    <div className="space-y-3">
      <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-line px-3 py-2 text-sm text-ink-2 hover:bg-surface-2">
        <Upload size={15} aria-hidden /> Choose a .csv file
        <input type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => void onFile(e.target.files?.[0])} />
      </label>
      <textarea className={`${inputClass} h-28 font-mono text-xs`} placeholder={CSV_EXAMPLE} value={text} onChange={(e) => setText(e.target.value)} aria-label="CSV content" />
      <Button onClick={() => importCsv.mutate(text, { onSuccess: setResult })} disabled={!text.trim() || importCsv.isPending}>
        Import CSV
      </Button>
      {importCsv.isError && <p className="text-sm text-critical">{importCsv.error.message}</p>}
      {result && (
        <div className="text-xs">
          <p className="text-ink">Imported {result.imported.length} row(s).</p>
          {result.errors.map((e) => (
            <p key={`${e.line}-${e.message}`} className="text-critical">
              Line {e.line}: {e.message}
            </p>
          ))}
        </div>
      )}
      <p className="text-xs text-muted">Columns: coin (CoinGecko id) or symbol, quantity, optional avg_cost_usd and notes.</p>
    </div>
  );
}

function AddressForm() {
  const importAddress = useImportAddress();
  const [chain, setChain] = useState("ethereum");
  const [address, setAddress] = useState("");
  const [result, setResult] = useState<AddressImportResult | null>(null);
  return (
    <div className="space-y-3">
      <p className="flex gap-2 rounded-lg border border-line p-2 text-xs text-ink-2">
        <ShieldAlert size={16} className="shrink-0" style={{ color: "var(--warning)" }} aria-hidden />
        Public address only. Lodestar never asks for a private key or seed phrase, and rejects anything that looks like one.
      </p>
      <select className={inputClass} value={chain} onChange={(e) => setChain(e.target.value)} aria-label="Chain">
        <option value="ethereum">Ethereum (ETH + POL, LINK, WBTC, USDC)</option>
        <option value="polygon">Polygon PoS (POL + WETH, LINK, USDC)</option>
        <option value="bitcoin">Bitcoin</option>
      </select>
      <input className={`${inputClass} font-mono text-xs`} placeholder={chain === "bitcoin" ? "bc1…" : "0x…"} value={address} onChange={(e) => setAddress(e.target.value)} autoComplete="off" spellCheck={false} aria-label="Public address" />
      <Button onClick={() => importAddress.mutate({ chain, address }, { onSuccess: setResult })} disabled={address.trim().length < 20 || importAddress.isPending}>
        Read balances
      </Button>
      {importAddress.isError && <p className="text-sm text-critical">{importAddress.error.message}</p>}
      {result && (
        <p className="text-xs text-ink">
          {result.source_label}: imported {result.imported.map((i) => `${num(i.quantity)} ${i.asset.symbol}`).join(", ") || "no balances"}
          {result.demo && " (demo balances)"}
        </p>
      )}
    </div>
  );
}

export function PortfolioPage() {
  const portfolio = usePortfolio();
  const remove = useRemoveHolding();
  if (portfolio.isLoading) return <Spinner />;
  const p = portfolio.data;

  return (
    <div className="space-y-6">
      {p && p.positions.length > 0 ? (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatTile label="Value" value={usd(p.total_value_usd)} delta={p.change_24h_pct} deltaLabel="24h" />
            <StatTile label="Cost basis" value={usd(p.total_cost_usd)} hint="Holdings with a recorded cost" />
            <StatTile label="Unrealised P&L" value={usd(p.total_pnl_usd)} delta={p.total_pnl_pct} deltaLabel="vs cost" />
          </div>
          <Card title="Positions">
            <AllocationBar
              variant="thin"
              slices={p.positions.filter((x) => x.value_usd).map((x) => ({ asset: x.asset, value_usd: x.value_usd ?? 0, weight_pct: x.weight_pct }))}
            />
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted">
                    <th className="pb-2 font-normal">Asset · source</th>
                    <th className="pb-2 text-right font-normal">Quantity</th>
                    <th className="pb-2 text-right font-normal">Price</th>
                    <th className="pb-2 text-right font-normal">24h</th>
                    <th className="pb-2 text-right font-normal">Value</th>
                    <th className="pb-2 text-right font-normal">Avg cost</th>
                    <th className="pb-2 text-right font-normal">P&L</th>
                    <th className="pb-2 text-right font-normal">Weight</th>
                    <th />
                  </tr>
                </thead>
                <tbody className="tabular">
                  {p.positions.map((pos, i) => (
                    <Fragment key={pos.asset.id}>
                      <tr className="border-t border-line">
                        <td className="py-2.5">
                          <span className="mr-2 inline-block h-2 w-2 rounded-sm" style={{ background: i < 6 ? `var(--series-${i + 1})` : "var(--muted)" }} aria-hidden />
                          <Link to={`/coins/${pos.asset.id}`} className="font-medium hover:text-accent">{pos.asset.symbol}</Link>
                        </td>
                        <td className="py-2.5 text-right">{num(pos.quantity)}</td>
                        <td className="py-2.5 text-right">{pos.price_stale ? <span className="text-muted">unavailable</span> : usd(pos.price_usd)}</td>
                        <td className="py-2.5 text-right"><ChangeText value={pos.change_24h_pct} /></td>
                        <td className="py-2.5 text-right">{usd(pos.value_usd)}</td>
                        <td className="py-2.5 text-right">{usd(pos.avg_cost_usd)}</td>
                        <td className="py-2.5 text-right">
                          {usd(pos.pnl_usd)}
                          <div className="text-xs"><ChangeText value={pos.pnl_pct} /></div>
                        </td>
                        <td className="py-2.5 text-right">{pos.weight_pct === null ? "—" : `${pos.weight_pct.toFixed(1)}%`}</td>
                        <td />
                      </tr>
                      {pos.holdings.map((h) => (
                        <tr key={h.id} className="text-xs text-ink-2">
                          <td className="py-1 pl-5">
                            {h.source_label}
                            {h.notes && <span className="ml-2 text-muted" title={h.notes}>· {h.notes.slice(0, 40)}</span>}
                          </td>
                          <td className="py-1 text-right">{num(h.quantity)}</td>
                          <td colSpan={3} />
                          <td className="py-1 text-right">{usd(h.avg_cost_usd)}</td>
                          <td colSpan={2} />
                          <td className="py-1 pl-3 text-right">
                            <button type="button" onClick={() => remove.mutate(h.id)} aria-label={`Remove ${pos.asset.symbol} from ${h.source_label}`} className="text-muted hover:text-critical">
                              <Trash2 size={14} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      ) : (
        <Empty>No holdings yet. Add them manually, import a CSV, or read balances from a public address.</Empty>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="Add manually"><ManualForm /></Card>
        <Card title="Import CSV"><CsvForm /></Card>
        <Card title="Import from a public address"><AddressForm /></Card>
      </div>
    </div>
  );
}
