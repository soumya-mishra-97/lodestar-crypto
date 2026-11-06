---
name: market-scanner
description: Rank the top-N liquid coins by trend, breakout, volume spike and strength against Bitcoin, computed in code. Use when the user asks which coins look interesting, wants a shortlist, or wants to scan the market or a watchlist.
---

# Market scanner

Part of Lodestar's Trader Skills: read-only research and **paper trading only**.

## What it does

Scores each of the top-N coins by market cap from 0 to 100: trend (40: close above the 20 and 50-day averages, 20 above 50, 20-day rising), breakout (20: close above the prior 20-day high, 10 if within 2%), volume (20: 7-day vs 30-day volume) and relative strength against Bitcoin over 30 days (20). Coins below the 24-hour volume floor are ranked last.

## How to run

From the repository root (no database or worker needed; prints JSON):

```bash
cd backend && PYTHONPATH=src uv run python -m lodestar.interfaces.skills market-scanner --top-n 20 [--min-volume-usd 5000000]
```

Data is synthetic (demo mode, `"data_mode": "demo"`) unless `LS_COINGECKO_API_KEY` or `LS_DATA_MODE=live` is set in `.env`. Say which mode the output came from.

## Output

`ranked[]`: `coingecko_id`, `symbol`, `score`, `trend_points`, `breakout`, `breakout_distance_pct`, `volume_ratio`, `rs_vs_btc_pct`, `volume_24h_usd`, `passes_liquidity`, `setup_kind`.

## Presenting it

Present the top five liquid coins as a shortlist with their score parts. Scanning many charts always finds something that looks like an edge: a high score is a reason to run `trade-plan` on the coin, not a signal.

## Rules when you present the result

- **Numbers come only from the JSON output.** Never compute, round into new figures, estimate or recall a price, level, percentage or count yourself. If a number is not in the output, say it is not available.
- **Tag every claim** as `fact` (observed provider value), `calculation` (computed by Lodestar code), `interpretation`, `scenario` (an if/then outcome, never a forecast) or `assumption`, and cite the evidence ids (for example `TIM-3`) it rests on. Drop any sentence you cannot trace to an evidence id.
- **No price targets, guarantees or "best time".** Timing is a set of conditions (entry zone, trigger, invalidation), never a moment to buy.
- **Small samples are said out loud.** If `sample_reliability` is `small` or `insufficient`, say the statistics are not reliable.
- **Paper trading only.** Lodestar never places orders, holds no exchange keys and has no trading permission. Do not suggest connecting one.
- **End with the risk disclaimer** from the output's `disclaimer` field, unchanged.
