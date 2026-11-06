---
name: report-verifier
description: Verify a trade-plan JSON: every claim must cite existing evidence, numbers must match it, the timing must cite the entry zone, trigger and invalidation, scenarios must be cited, size must respect the max loss, no 'best time' language, and the disclaimer must be intact. Use before showing or sharing any trade plan.
---

# Report verifier

Part of Lodestar's Trader Skills: read-only research and **paper trading only**.

## What it does

Runs the claim rules C1-C9 (traceable ids, matching numbers, allowed tags, no guarantees or targets) and the trade-plan rules P1-P7 on a file containing `draft` and `evidence` (for example the output of `trade-plan`). Exits with status 1 when verification fails.

## How to run

From the repository root (no database or worker needed; prints JSON):

```bash
cd backend && PYTHONPATH=src uv run python -m lodestar.interfaces.skills report-verifier --file plan.json
```

Data is synthetic (demo mode, `"data_mode": "demo"`) unless `LS_COINGECKO_API_KEY` or `LS_DATA_MODE=live` is set in `.env`. Say which mode the output came from.

## Output

`verification`: `passed`, `checked_claims`, `findings[]` (location, rule, message, claim_text).

## Presenting it

If `passed` is false, do not present the plan; list the findings instead. Never edit numbers to make a plan pass.

## Rules when you present the result

- **Numbers come only from the JSON output.** Never compute, round into new figures, estimate or recall a price, level, percentage or count yourself. If a number is not in the output, say it is not available.
- **Tag every claim** as `fact` (observed provider value), `calculation` (computed by Lodestar code), `interpretation`, `scenario` (an if/then outcome, never a forecast) or `assumption`, and cite the evidence ids (for example `TIM-3`) it rests on. Drop any sentence you cannot trace to an evidence id.
- **No price targets, guarantees or "best time".** Timing is a set of conditions (entry zone, trigger, invalidation), never a moment to buy.
- **Small samples are said out loud.** If `sample_reliability` is `small` or `insufficient`, say the statistics are not reliable.
- **Paper trading only.** Lodestar never places orders, holds no exchange keys and has no trading permission. Do not suggest connecting one.
- **End with the risk disclaimer** from the output's `disclaimer` field, unchanged.
