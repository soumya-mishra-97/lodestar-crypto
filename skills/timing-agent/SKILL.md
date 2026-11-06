---
name: timing-agent
description: Turn a coin's chart into rule-based trade conditions: the setup (breakout, pullback, trend reclaim), entry zone, trigger and invalidation level. Use when the user asks when or where to enter, or what would invalidate a setup. Never answers with a 'best time'.
---

# Timing agent

Part of Lodestar's Trader Skills: read-only research and **paper trading only**.

## What it does

Picks the setup in code, then computes the trigger level, an entry zone (trigger to trigger + 0.5 ATR), the invalidation level (trigger - 2 ATR) and a profit-taking rule at 2R. Signals use the daily close; nothing looks ahead. Evidence ids start with `TIM`.

## How to run

From the repository root (no database or worker needed; prints JSON):

```bash
cd backend && PYTHONPATH=src uv run python -m lodestar.interfaces.skills timing-agent --coin solana
```

Data is synthetic (demo mode, `"data_mode": "demo"`) unless `LS_COINGECKO_API_KEY` or `LS_DATA_MODE=live` is set in `.env`. Say which mode the output came from.

## Output

`timing`: `kind`, `status` (`active`/`extended`/`waiting`), `trigger_text`, `level`, `entry_low`, `entry_high`, `invalidation`, `profit_level`, `trend_up`, `atr`; `evidence[]` with `entry_zone_low`, `entry_zone_high`, `trigger_level`, `invalidation_level`.

## Presenting it

Always state all four: entry zone, trigger, invalidation, and that these are conditions, not predictions. Never say "now is the time", "best time" or similar.

## Rules when you present the result

- **Numbers come only from the JSON output.** Never compute, round into new figures, estimate or recall a price, level, percentage or count yourself. If a number is not in the output, say it is not available.
- **Tag every claim** as `fact` (observed provider value), `calculation` (computed by Lodestar code), `interpretation`, `scenario` (an if/then outcome, never a forecast) or `assumption`, and cite the evidence ids (for example `TIM-3`) it rests on. Drop any sentence you cannot trace to an evidence id.
- **No price targets, guarantees or "best time".** Timing is a set of conditions (entry zone, trigger, invalidation), never a moment to buy.
- **Small samples are said out loud.** If `sample_reliability` is `small` or `insufficient`, say the statistics are not reliable.
- **Paper trading only.** Lodestar never places orders, holds no exchange keys and has no trading permission. Do not suggest connecting one.
- **End with the risk disclaimer** from the output's `disclaimer` field, unchanged.
