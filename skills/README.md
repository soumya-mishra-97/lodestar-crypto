# Lodestar trader skills

Eleven skills plus a coordinator, each packaged as a Claude skill (`<name>/SKILL.md`) that runs
the same code as the app through `python -m lodestar.interfaces.skills`, with no database or worker.

| Skill | Purpose |
|---|---|
| [`market-scanner`](market-scanner/SKILL.md) | Market scanner |
| [`news-event-scout`](news-event-scout/SKILL.md) | News and event scout |
| [`sentiment-reader`](sentiment-reader/SKILL.md) | Sentiment reader |
| [`fundamentals-analyst`](fundamentals-analyst/SKILL.md) | Fundamentals analyst |
| [`technical-analyst`](technical-analyst/SKILL.md) | Technical analyst |
| [`liquidity-checker`](liquidity-checker/SKILL.md) | Liquidity checker |
| [`timing-agent`](timing-agent/SKILL.md) | Timing agent |
| [`scenario-stats-engine`](scenario-stats-engine/SKILL.md) | Scenario statistics engine |
| [`risk-position-sizer`](risk-position-sizer/SKILL.md) | Risk and position sizer |
| [`backtester-paper-trader`](backtester-paper-trader/SKILL.md) | Backtester and paper trader |
| [`report-verifier`](report-verifier/SKILL.md) | Report verifier |
| [`trade-plan`](trade-plan/SKILL.md) | Trade plan (coordinator) |

To use them with Claude Code, copy or symlink the folders into `.claude/skills/` (project) or
`~/.claude/skills/` (personal). Every number in a skill's output is computed in code from provider
data; the skills only explain it. Paper trading only: nothing here can place an order.
