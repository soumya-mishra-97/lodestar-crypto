---
name: backtester-paper-trader
description: Backtest a coin's current setup with fees and slippage, an out-of-sample split and walk-forward tests, and report overfitting warnings. Use when the user asks whether a setup has worked historically. Paper trading itself runs in the app.
---

# Backtester and paper trader

Part of Lodestar's Trader Skills: read-only research and **paper trading only**.

## What it does

Signals on the close of day i fill at the open of day i+1 (no look-ahead); stop first if a bar touches both levels. Parameters are fitted on the first 70% of history (a 9-combination grid) and judged on the rest; walk-forward refits every 60 days on the prior 240. Warnings fire for: fewer than 10 out-of-sample trades; out-of-sample Sharpe below half of in-sample; profitable in-sample but losing out-of-sample; chosen parameters far above the grid median; walk-forward picking different parameters in most windows; walk-forward trailing buy-and-hold; most profit from two trades; under two years of history; bars approximated from closes. Evidence ids start with `BKT`.

## How to run

From the repository root (no database or worker needed; prints JSON):

```bash
cd backend && PYTHONPATH=src uv run python -m lodestar.interfaces.skills backtester-paper-trader --coin ethereum --fee-bps 10 --slippage-bps 5
```

Data is synthetic (demo mode, `"data_mode": "demo"`) unless `LS_COINGECKO_API_KEY` or `LS_DATA_MODE=live` is set in `.env`. Say which mode the output came from.

## Output

`backtest`: `in_sample`, `out_of_sample`, `walk_forward` (trades, win rate, total return, max drawdown, Sharpe, buy-and-hold), `warnings[]`, `chosen_params`, `assumptions[]`.

## Presenting it

Lead with out-of-sample and walk-forward results, not in-sample. Repeat every overfitting warning. For paper trading, approve a trade plan in the app and use **Paper trade this plan**; the engine applies the same rules to new daily bars with simulated money.

## Rules when you present the result

- **Numbers come only from the JSON output.** Never compute, round into new figures, estimate or recall a price, level, percentage or count yourself. If a number is not in the output, say it is not available.
- **Tag every claim** as `fact` (observed provider value), `calculation` (computed by Lodestar code), `interpretation`, `scenario` (an if/then outcome, never a forecast) or `assumption`, and cite the evidence ids (for example `TIM-3`) it rests on. Drop any sentence you cannot trace to an evidence id.
- **No price targets, guarantees or "best time".** Timing is a set of conditions (entry zone, trigger, invalidation), never a moment to buy.
- **Small samples are said out loud.** If `sample_reliability` is `small` or `insufficient`, say the statistics are not reliable.
- **Paper trading only.** Lodestar never places orders, holds no exchange keys and has no trading permission. Do not suggest connecting one.
- **End with the risk disclaimer** from the output's `disclaimer` field, unchanged.
