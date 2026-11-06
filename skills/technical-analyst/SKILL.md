---
name: technical-analyst
description: Describe a coin's trend, momentum and volatility from daily candles: moving averages, RSI, MACD, Bollinger bands, volatility, support/resistance and drawdown. Use when the user asks about the chart or trend.
---

# Technical analyst

Part of Lodestar's Trader Skills: read-only research and **paper trading only**.

## What it does

All indicators are computed in code from exchange candles (Kraken) or CoinGecko closes. Evidence ids start with `TEC`.

## How to run

From the repository root (no database or worker needed; prints JSON):

```bash
cd backend && PYTHONPATH=src uv run python -m lodestar.interfaces.skills technical-analyst --coin polygon-ecosystem-token
```

Data is synthetic (demo mode, `"data_mode": "demo"`) unless `LS_COINGECKO_API_KEY` or `LS_DATA_MODE=live` is set in `.env`. Say which mode the output came from.

## Output

`claims[]`, `signals[]`, `evidence[]` (`sma_20`, `sma_50`, `sma_200`, `rsi_14`, `macd_line`, `bollinger_pct_b`, `volatility_30d_pct`, `support_30d`, `resistance_30d`, `max_drawdown_1y_pct`...).

## Presenting it

Describe the state of the chart; do not extrapolate it into a prediction.

## Rules when you present the result

- **Numbers come only from the JSON output.** Never compute, round into new figures, estimate or recall a price, level, percentage or count yourself. If a number is not in the output, say it is not available.
- **Tag every claim** as `fact` (observed provider value), `calculation` (computed by Lodestar code), `interpretation`, `scenario` (an if/then outcome, never a forecast) or `assumption`, and cite the evidence ids (for example `TIM-3`) it rests on. Drop any sentence you cannot trace to an evidence id.
- **No price targets, guarantees or "best time".** Timing is a set of conditions (entry zone, trigger, invalidation), never a moment to buy.
- **Small samples are said out loud.** If `sample_reliability` is `small` or `insufficient`, say the statistics are not reliable.
- **Paper trading only.** Lodestar never places orders, holds no exchange keys and has no trading permission. Do not suggest connecting one.
- **End with the risk disclaimer** from the output's `disclaimer` field, unchanged.
