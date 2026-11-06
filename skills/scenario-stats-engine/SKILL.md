---
name: scenario-stats-engine
description: Show bull, base and bear scenarios for a coin's current setup from historical analogs: win rate, average and median return, max drawdown, sample size and 95% confidence intervals. Use when the user asks about odds, expected outcomes or what happened in similar setups.
---

# Scenario statistics engine

Part of Lodestar's Trader Skills: read-only research and **paper trading only**.

## What it does

Finds past, non-overlapping occurrences of the same setup, enters at the next open, measures the return after the horizon net of fees and slippage, and splits outcomes into bull/base/bear at +/- half a typical horizon move. Wilson intervals for rates and t intervals for means. Evidence ids start with `SCE`.

## How to run

From the repository root (no database or worker needed; prints JSON):

```bash
cd backend && PYTHONPATH=src uv run python -m lodestar.interfaces.skills scenario-stats-engine --coin bitcoin --horizon 14
```

Data is synthetic (demo mode, `"data_mode": "demo"`) unless `LS_COINGECKO_API_KEY` or `LS_DATA_MODE=live` is set in `.env`. Say which mode the output came from.

## Output

`scenarios`: `overall` (`n`, `win_rate_pct`, `win_rate_ci`, `mean_pct`, `mean_ci`, `median_pct`, `worst_drawdown_pct`, `reliability`), `scenarios[]` (name, definition, count, probability_pct, probability_ci, mean_pct, median_pct, worst_drawdown_pct).

## Presenting it

Always give the sample size next to every rate. If `reliability` is `small` (n < 30) or `insufficient` (n < 10), say the sample is too small to trust. Frequencies describe the past, not probabilities for next time.

## Rules when you present the result

- **Numbers come only from the JSON output.** Never compute, round into new figures, estimate or recall a price, level, percentage or count yourself. If a number is not in the output, say it is not available.
- **Tag every claim** as `fact` (observed provider value), `calculation` (computed by Lodestar code), `interpretation`, `scenario` (an if/then outcome, never a forecast) or `assumption`, and cite the evidence ids (for example `TIM-3`) it rests on. Drop any sentence you cannot trace to an evidence id.
- **No price targets, guarantees or "best time".** Timing is a set of conditions (entry zone, trigger, invalidation), never a moment to buy.
- **Small samples are said out loud.** If `sample_reliability` is `small` or `insufficient`, say the statistics are not reliable.
- **Paper trading only.** Lodestar never places orders, holds no exchange keys and has no trading permission. Do not suggest connecting one.
- **End with the risk disclaimer** from the output's `disclaimer` field, unchanged.
