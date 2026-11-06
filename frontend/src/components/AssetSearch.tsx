import { Plus, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useAddCoin, useSearch } from "@/api/hooks";

/** Search any coin; selecting it adds it (tracked + watched) and opens its live pipeline run. */
export function AssetSearch() {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const add = useAddCoin();
  const ref = useRef<HTMLInputElement>(null);
  const { data = [], isFetching } = useSearch(query);

  useEffect(() => {
    const t = setTimeout(() => setQuery(input.trim()), 250); // debounce upstream calls
    return () => clearTimeout(t);
  }, [input]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const results = data.slice(0, 8);
  const select = async (coingeckoId: string) => {
    const { asset, run } = await add.mutateAsync(coingeckoId);
    setInput("");
    setOpen(false);
    navigate(run ? `/pipeline/${run.id}` : `/coins/${asset.id}`);
  };

  return (
    <div className="relative w-full max-w-md">
      <label className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 focus-within:border-accent">
        <Search size={16} className="text-muted" aria-hidden />
        <input
          ref={ref}
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setOpen(true);
            setActive(0);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, results.length - 1));
            if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
            if (e.key === "Enter" && results[active]) void select(results[active].coingecko_id);
          }}
          maxLength={64}
          placeholder="Add a coin (e.g. Polygon, SOL)…"
          aria-label="Search cryptocurrencies"
          className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-muted"
        />
        <kbd className="hidden rounded border border-line px-1.5 text-[10px] text-muted sm:block">⌘K</kbd>
      </label>
      {open && query.length >= 2 && (
        <ul className="absolute z-20 mt-2 w-full overflow-hidden rounded-xl border border-line bg-surface shadow-2xl" role="listbox">
          {isFetching && results.length === 0 && <li className="px-4 py-3 text-sm text-ink-2">Searching…</li>}
          {!isFetching && results.length === 0 && <li className="px-4 py-3 text-sm text-ink-2">No matches</li>}
          {results.map((c, i) => (
            <li key={c.coingecko_id} role="option" aria-selected={i === active}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => void select(c.coingecko_id)}
                className={`flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm ${i === active ? "bg-surface-2" : ""}`}
              >
                {c.thumb_url ? (
                  <img src={c.thumb_url} alt="" className="h-5 w-5 rounded-full" referrerPolicy="no-referrer" />
                ) : (
                  <span className="h-5 w-5 rounded-full bg-surface-2" />
                )}
                <span className="flex-1 truncate text-ink">{c.name}</span>
                <span className="text-xs text-ink-2">{c.symbol}</span>
                <span className="w-12 text-right text-xs text-muted tabular">{c.market_cap_rank ? `#${c.market_cap_rank}` : ""}</span>
                <Plus size={14} className="text-muted" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      {add.isPending && <p className="mt-1 text-xs text-ink-2">Adding and starting analysis…</p>}
      {add.isError && <p className="mt-1 text-xs text-critical">{add.error.message}</p>}
    </div>
  );
}
