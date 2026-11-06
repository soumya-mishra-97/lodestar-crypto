---
name: risk-position-sizer
description: Size a paper position from a maximum loss: units and notional from the stop distance, then capped by concentration, order-book liquidity (slippage) and correlation. Use when the user asks how much to buy or how to size a trade.
---

# Risk and position sizer

Part of Lodestar's Trader Skills: read-only research and **paper trading only**.

## What it does

size = max loss / (entry - stop, plus costs), then capped at the max position %, at the largest size whose order-book slippage stays under the limit, and reduced for correlation with open positions. Also scores short-term risk. Evidence ids start with `SIZ`.

## How to run

From the repository root (no database or worker needed; prints JSON):

```bash
cd backend && PYTHONPATH=src uv run python -m lodestar.interfaces.skills risk-position-sizer --coin solana --account 10000 --max-loss-pct 1
```

Data is synthetic (demo mode, `"data_mode": "demo"`) unless `LS_COINGECKO_API_KEY` or `LS_DATA_MODE=live` is set in `.env`. Say which mode the output came from.

## Output

`sizing`: `units`, `notional_usd`, `pct_of_equity`, `max_loss_usd`, `loss_at_stop_usd`, `stop_distance_pct`, `expected_slippage_pct`, `binding` (which limit decided the size), `warnings`, `risk` (level, score, factors).

## Presenting it

State the max loss the size was derived from and which limit was binding. This is a paper size for simulated money.

## Rules when you present the result

- **Numbers come only from the JSON output.** Never compute, round into new figures, estimate or recall a price, level, percentage or count yourself. If a number is not in the output, say it is not available.
- **Tag every claim** as `fact` (observed provider value), `calculation` (computed by Lodestar code), `interpretation`, `scenario` (an if/then outcome, never a forecast) or `assumption`, and cite the evidence ids (for example `TIM-3`) it rests on. Drop any sentence you cannot trace to an evidence id.
- **No price targets, guarantees or "best time".** Timing is a set of conditions (entry zone, trigger, invalidation), never a moment to buy.
- **Small samples are said out loud.** If `sample_reliability` is `small` or `insufficient`, say the statistics are not reliable.
- **Paper trading only.** Lodestar never places orders, holds no exchange keys and has no trading permission. Do not suggest connecting one.
- **End with the risk disclaimer** from the output's `disclaimer` field, unchanged.
