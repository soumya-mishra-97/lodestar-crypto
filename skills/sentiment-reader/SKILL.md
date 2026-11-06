---
name: sentiment-reader
description: Read market sentiment for a coin: Fear & Greed index, headline flow, perpetual futures funding rate and prediction-market odds. Use when the user asks about sentiment, positioning or funding.
---

# Sentiment reader

Part of Lodestar's Trader Skills: read-only research and **paper trading only**.

## What it does

Combines the Fear & Greed index, recent headline counts, the Kraken Futures funding rate (hourly and annualised) and optional Polymarket odds into tagged claims with `SEN` and `DAT` evidence.

## How to run

From the repository root (no database or worker needed; prints JSON):

```bash
cd backend && PYTHONPATH=src uv run python -m lodestar.interfaces.skills sentiment-reader --coin bitcoin
```

Data is synthetic (demo mode, `"data_mode": "demo"`) unless `LS_COINGECKO_API_KEY` or `LS_DATA_MODE=live` is set in `.env`. Say which mode the output came from.

## Output

`claims[]`, `signals[]`, `evidence[]` including `fear_greed`, `fear_greed_label`, `funding_rate_annual_pct`, `headline_count_7d`, `market_<n>_yes_pct`.

## Presenting it

Extreme sentiment is context for risk, not a timing signal.

## Rules when you present the result

- **Numbers come only from the JSON output.** Never compute, round into new figures, estimate or recall a price, level, percentage or count yourself. If a number is not in the output, say it is not available.
- **Tag every claim** as `fact` (observed provider value), `calculation` (computed by Lodestar code), `interpretation`, `scenario` (an if/then outcome, never a forecast) or `assumption`, and cite the evidence ids (for example `TIM-3`) it rests on. Drop any sentence you cannot trace to an evidence id.
- **No price targets, guarantees or "best time".** Timing is a set of conditions (entry zone, trigger, invalidation), never a moment to buy.
- **Small samples are said out loud.** If `sample_reliability` is `small` or `insufficient`, say the statistics are not reliable.
- **Paper trading only.** Lodestar never places orders, holds no exchange keys and has no trading permission. Do not suggest connecting one.
- **End with the risk disclaimer** from the output's `disclaimer` field, unchanged.
