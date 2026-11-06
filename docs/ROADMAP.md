# Roadmap

Status key: ✅ done in this repository · 🔜 next · 💡 later

## Phase 1: Foundation ✅
- ✅ Clean Architecture (domain / application / infrastructure / interfaces), typed config, composition root, structured logging, health probes, metrics
- ✅ PostgreSQL schema + Alembic migrations (`alembic check` clean in CI), Redis
- ✅ Auth: single-user local mode; password mode with Argon2id, JWT + rotating refresh cookie, RBAC, rate limits (required in production)

## Phase 2: Data ✅
- ✅ CoinGecko, Kraken (candles + ticker), DefiLlama (TVL + reference price), Fear & Greed, RSS news, optional Polymarket
- ✅ Three-way price reconciliation with mismatch flags; retries, circuit breakers, Redis caching
- ✅ Demo mode: deterministic synthetic data for every port, with a visible banner

## Phase 3: Agentic pipeline ✅
- ✅ LangGraph: Data → four parallel analysts → Portfolio → Report writer → Verifier → Human approval, Postgres checkpoints
- ✅ ReAct analysts with read-only tools and a step limit; Claude or scripted policy
- ✅ Evidence bundle with namespaced ids and lineage; tagged claims; fail-closed verifier with at most two repair loops
- ✅ Live event streaming (Postgres audit trail + Redis Streams + SSE); Celery worker + beat (daily reports)

## Phase 4: Product ✅
- ✅ Overview, Coin detail (candles + indicators), Pipeline, Portfolio (manual, CSV, public address), Reports (approve/reject, Markdown/PDF export), Settings
- ✅ CI with a Docker stack acceptance smoke test

## Phase 4b: Trader Skills (paper trading) ✅
- ✅ Market scanner over the top-N liquid coins or the watchlist, with a liquidity floor and a ranked shortlist
- ✅ Second LangGraph graph: five parallel skills → timing → scenario statistics → sizing → backtest → writer → verifier → human approval
- ✅ Scenario statistics with sample sizes, Wilson/t intervals and reliability flags; backtester with costs, out-of-sample and walk-forward tests and overfitting warnings
- ✅ Position sizing from max loss with concentration, order-book liquidity and correlation caps
- ✅ Paper-trading engine and portfolio with a Bitcoin benchmark; hourly tick on new daily bars
- ✅ Trade-plan verifier rules (P1–P7); every skill packaged as a Claude skill (`skills/`)

## Phase 5: Evaluation and hardening 🔜
- 🔜 **Report eval set**: freeze ~30 runs' evidence bundles (bull, bear, thin liquidity, missing data, price mismatch, injection headlines) and score verifier pass rate, repair loops, dropped claims and reviewer ratings per prompt version; gate prompt changes on it in CI
- 🔜 **Backtest the scorers**: replay 2-3 years of daily history and measure forward 7/30/180-day returns by stance bucket; tune weights in `domain/scoring.py` only on out-of-sample improvement
- 🔜 Playwright end-to-end tests (add coin → watch timeline → approve → export; scan → trade plan → paper trade)
- 🔜 Track paper-trading results against each plan's stated scenarios (calibration of the scenario frequencies)
- 🔜 Portfolio value history (TimescaleDB hypertable) for drawdown of *your* holdings
- 🔜 Alerts (email/Telegram) on stance changes, risk-level changes and price mismatches

## Phase 6: Extensions 💡
- 💡 Read-only **MCP server** (`search_assets`, `get_latest_report`, `get_portfolio`, `get_run_events`) to ask Claude about your verified data
- 💡 More chains and tokens for wallet import (token lists, Solana); exchange import via read-only API keys
- 💡 On-chain metrics (active addresses, holder concentration, unlock schedules) as a fifth analyst
- 💡 TOTP / passkeys if the app is exposed beyond localhost

## Deployment path

| Stage | Setup |
|---|---|
| Local | `make up` (Docker Compose) or the `make dev-*` processes |
| Personal cloud | One small VM (2 vCPU / 2 GB) running the same compose file behind Caddy for HTTPS, `LS_AUTH_MODE=password`, nightly `pg_dump` |
| Managed | Release images from GHCR → Fly.io / Render / ECS; managed Postgres + Redis; secrets in the platform's store; scale `worker` horizontally |
