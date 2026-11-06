---
name: trade-plan
description: Run the whole trader-skills pipeline for one coin and return a verified paper-trading plan card: setup, entry zone, trigger, invalidation, size from max loss, bull/base/bear scenarios with sample sizes, backtest with overfitting warnings, risk level and evidence ids. Use when the user asks for a trade plan, a setup review or 'should I trade X'.
---

# Trade plan (coordinator)

Part of Lodestar's Trader Skills: read-only research and **paper trading only**.

## What it does

Collects data, runs the five analysis skills in parallel (technical, fundamentals, sentiment, news/events, liquidity) with read-only tools, then the timing agent, scenario statistics, position sizer and backtester, writes the card from evidence and verifies it (same rules as `report-verifier`). In the app the same flow runs as a LangGraph pipeline, streams every step to the Pipeline screen and waits for human approval.

## How to run

From the repository root (no database or worker needed; prints JSON):

```bash
cd backend && PYTHONPATH=src uv run python -m lodestar.interfaces.skills trade-plan --coin polygon-ecosystem-token --account 10000 --max-loss-pct 1
```

Data is synthetic (demo mode, `"data_mode": "demo"`) unless `LS_COINGECKO_API_KEY` or `LS_DATA_MODE=live` is set in `.env`. Say which mode the output came from.

## Output

`card` (setup, timing, size, risk, scenarios, backtest, scanner), `draft` (headline, setup, timing, scenarios, risk, invalidation, evidence and assumptions claims), `verification`, `evidence[]`, `disclaimer`.

## Presenting it

Present the card in this order: headline, setup, entry zone / trigger / invalidation, size and max loss, risk level, scenarios with sample size and reliability, backtest (out-of-sample first) and warnings, what invalidates it, evidence ids, disclaimer. If `verification.passed` is false, show the findings instead of the plan.

## Rules when you present the result

- **Numbers come only from the JSON output.** Never compute, round into new figures, estimate or recall a price, level, percentage or count yourself. If a number is not in the output, say it is not available.
- **Tag every claim** as `fact` (observed provider value), `calculation` (computed by Lodestar code), `interpretation`, `scenario` (an if/then outcome, never a forecast) or `assumption`, and cite the evidence ids (for example `TIM-3`) it rests on. Drop any sentence you cannot trace to an evidence id.
- **No price targets, guarantees or "best time".** Timing is a set of conditions (entry zone, trigger, invalidation), never a moment to buy.
- **Small samples are said out loud.** If `sample_reliability` is `small` or `insufficient`, say the statistics are not reliable.
- **Paper trading only.** Lodestar never places orders, holds no exchange keys and has no trading permission. Do not suggest connecting one.
- **End with the risk disclaimer** from the output's `disclaimer` field, unchanged.
