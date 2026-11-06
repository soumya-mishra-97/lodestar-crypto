---
name: fundamentals-analyst
description: Summarise a coin's fundamentals from data: market cap, FDV and dilution, DefiLlama TVL, and chain fees and revenue. Use when the user asks about valuation, usage or token economics.
---

# Fundamentals analyst

Part of Lodestar's Trader Skills: read-only research and **paper trading only**.

## What it does

Computes dilution (FDV vs market cap), TVL ratios and 30-day chain fees and revenue where DefiLlama covers the chain. Coins that are not covered get an explicit `assumption` claim saying so. Evidence ids start with `FUN` and `DAT`.

## How to run

From the repository root (no database or worker needed; prints JSON):

```bash
cd backend && PYTHONPATH=src uv run python -m lodestar.interfaces.skills fundamentals-analyst --coin ethereum
```

Data is synthetic (demo mode, `"data_mode": "demo"`) unless `LS_COINGECKO_API_KEY` or `LS_DATA_MODE=live` is set in `.env`. Say which mode the output came from.

## Output

`claims[]`, `signals[]`, `evidence[]` including `fdv_to_mcap`, `circulating_ratio_pct`, `turnover_pct`, and `tvl_usd`, `chain_fees_30d_usd`, `chain_revenue_30d_usd` when available.

## Presenting it

Missing coverage is a data gap, not a negative signal: say so plainly.

## Rules when you present the result

- **Numbers come only from the JSON output.** Never compute, round into new figures, estimate or recall a price, level, percentage or count yourself. If a number is not in the output, say it is not available.
- **Tag every claim** as `fact` (observed provider value), `calculation` (computed by Lodestar code), `interpretation`, `scenario` (an if/then outcome, never a forecast) or `assumption`, and cite the evidence ids (for example `TIM-3`) it rests on. Drop any sentence you cannot trace to an evidence id.
- **No price targets, guarantees or "best time".** Timing is a set of conditions (entry zone, trigger, invalidation), never a moment to buy.
- **Small samples are said out loud.** If `sample_reliability` is `small` or `insufficient`, say the statistics are not reliable.
- **Paper trading only.** Lodestar never places orders, holds no exchange keys and has no trading permission. Do not suggest connecting one.
- **End with the risk disclaimer** from the output's `disclaimer` field, unchanged.
