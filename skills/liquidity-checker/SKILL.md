---
name: liquidity-checker
description: Check whether a coin can be traded in size: 24h volume, order-book spread and depth, and the expected slippage for $1k, $5k, $10k, $50k and $250k orders from walking the live book. Use when the user asks about liquidity, slippage or how big a position can be.
---

# Liquidity checker

Part of Lodestar's Trader Skills: read-only research and **paper trading only**.

## What it does

Walks the Kraken order book (bids and asks) to compute the spread, the depth within 2% of mid and a slippage curve. Evidence ids start with `LIQ`.

## How to run

From the repository root (no database or worker needed; prints JSON):

```bash
cd backend && PYTHONPATH=src uv run python -m lodestar.interfaces.skills liquidity-checker --coin solana
```

Data is synthetic (demo mode, `"data_mode": "demo"`) unless `LS_COINGECKO_API_KEY` or `LS_DATA_MODE=live` is set in `.env`. Say which mode the output came from.

## Output

`claims[]`, `evidence[]` including `book_spread_pct`, `book_depth_2pct_usd`, `slippage_<order size in USD>` (percent), `depth_band_pct`, `reference_order_usd`.

## Presenting it

If no order book is available (the pair is not listed), say slippage could not be measured.

## Rules when you present the result

- **Numbers come only from the JSON output.** Never compute, round into new figures, estimate or recall a price, level, percentage or count yourself. If a number is not in the output, say it is not available.
- **Tag every claim** as `fact` (observed provider value), `calculation` (computed by Lodestar code), `interpretation`, `scenario` (an if/then outcome, never a forecast) or `assumption`, and cite the evidence ids (for example `TIM-3`) it rests on. Drop any sentence you cannot trace to an evidence id.
- **No price targets, guarantees or "best time".** Timing is a set of conditions (entry zone, trigger, invalidation), never a moment to buy.
- **Small samples are said out loud.** If `sample_reliability` is `small` or `insufficient`, say the statistics are not reliable.
- **Paper trading only.** Lodestar never places orders, holds no exchange keys and has no trading permission. Do not suggest connecting one.
- **End with the risk disclaimer** from the output's `disclaimer` field, unchanged.
