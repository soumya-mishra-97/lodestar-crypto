# Lodestar

**A personal, read-only crypto research platform with an agentic, evidence-grounded workflow.**

Add any coin and a pipeline of specialist agents analyses it. You get separate short-term and long-term assessments, each with a risk level, and every sentence is tagged and traceable to evidence. A verifier checks the report, then you approve it before it is published.

**Trader Skills** add a market scanner, per-coin trade plans (entry zone, trigger, invalidation, size from max loss, bull/base/bear statistics, backtest) and a **paper-trading** portfolio.

> **Read-only and paper only.** Lodestar never asks for or stores private keys, never signs anything and never places an order. There is no exchange client with order methods in the code and no setting for exchange keys with trading rights. Nothing here is financial advice.

![Overview](docs/images/overview.png)

---

## Contents

1. [What Lodestar does](#1-what-lodestar-does)
2. [Screens](#2-screens)
3. [Quick start with Docker](#3-quick-start-with-docker)
4. [Running without Docker (local development)](#4-running-without-docker-local-development)
5. [Core ideas: evidence, claims, verifier, approval](#5-core-ideas-evidence-claims-verifier-approval)
6. [Architecture](#6-architecture)
   - [6.1 System overview](#61-system-overview)
   - [6.2 Clean Architecture layers](#62-clean-architecture-layers)
   - [6.3 Life of a request: adding a coin](#63-life-of-a-request-adding-a-coin)
   - [6.4 The analysis pipeline](#64-the-analysis-pipeline)
   - [6.5 Analysts: ReAct loops with read-only tools](#65-analysts-react-loops-with-read-only-tools)
   - [6.6 The verifier](#66-the-verifier)
   - [6.7 Human approval and resume](#67-human-approval-and-resume)
   - [6.8 Live streaming (SSE)](#68-live-streaming-sse)
   - [6.9 Trader Skills (paper trading only)](#69-trader-skills-paper-trading-only)
   - [6.10 Data sources and demo mode](#610-data-sources-and-demo-mode)
   - [6.11 Claude integration](#611-claude-integration)
   - [6.12 Background jobs](#612-background-jobs)
   - [6.13 Data model](#613-data-model)
   - [6.14 Reliability](#614-reliability)
   - [6.15 Technology choices](#615-technology-choices)
7. [Folder structure](#7-folder-structure)
8. [HTTP API](#8-http-api)
9. [Trader Skills as Claude skills](#9-trader-skills-as-claude-skills)
10. [Configuration](#10-configuration)
11. [Testing and quality](#11-testing-and-quality)
12. [CI/CD](#12-cicd)
13. [Security](#13-security)
14. [Troubleshooting](#14-troubleshooting)
15. [Extending Lodestar](#15-extending-lodestar)
16. [Roadmap and further reading](#16-roadmap-and-further-reading)
17. [Disclaimer](#17-disclaimer)

---

## 1. What Lodestar does

| You do | Lodestar does |
|---|---|
| Search for a coin (⌘K) and add it | Tracks and watches it, starts a pipeline run and streams every step live |
| Wait a few seconds | Collects market data from several providers, reconciles prices, runs four analysts in parallel, writes a report, verifies every claim |
| Review the report | Shows short-term and long-term stances and risk levels, tagged claims with evidence ids, and data-quality checks. You approve or reject |
| Track your holdings | Takes manual entry, CSV import, or a read-only import from a **public** Ethereum, Polygon or Bitcoin address, then shows P&L, weights and portfolio risk |
| Run the scanner | Ranks the most liquid coins 0–100 on trend, breakout, volume and strength against Bitcoin, then shortlists the best |
| Build a trade plan | Runs a second pipeline: five skills, then timing, scenario statistics, position sizing and a backtest. It produces a verified trade-plan card |
| Paper trade an approved plan | Simulates the position on completed daily bars, after fees, against a Bitcoin buy-and-hold benchmark |
| Nothing | Writes daily reports for every watchlisted coin and updates paper positions every hour |

### What makes it trustworthy

- **All numbers are computed in code.** Prices come from named providers. Indicators, scores, stances, risk levels, statistics, sizes and portfolio maths come from deterministic code. The model only explains an evidence bundle. It cannot add or change a figure.
- **Every claim is tagged and cited.** Each claim is a `fact`, `calculation`, `interpretation`, `scenario` or `assumption`, with evidence ids (`DAT-01`, `TEC-04`, `RSK-07`…).
- **A verifier fails closed.**
  - It rejects unknown ids, missing citations and numbers that don't match their evidence.
  - It also rejects guarantees, price targets, buy/sell instructions, "best time to buy" timing and an altered disclaimer.
  - The writer gets two attempts to repair. If both fail, the run fails and nothing is published.
- **A human approves.** A verified report waits for your decision before it is published.
- **Sources are reconciled.** Price is compared across CoinGecko, Kraken and DefiLlama. A disagreement is flagged as evidence, as a risk factor and in the UI.
- **Everything is visible.** Every step streams its status, inputs, outputs, tool calls and evidence ids to the Pipeline screen, and is stored as an audit trail.

---

## 2. Screens

| Screen | What you see |
|---|---|
| **Overview** | Portfolio value, short- and long-term portfolio risk, allocation, watchlist with stances, risk and 30-day sparklines, latest report, recent runs |
| **Coin detail** | Exchange candles with SMA 20/50/200 and Bollinger overlays, RSI panel, both assessments with itemised risk, tagged claims, evidence bundle, price reconciliation, approval, "Build trade plan" |
| **Pipeline** | Live run timeline: data → four parallel analysts (with each ReAct tool call) → portfolio → writer → verifier (with repair attempts) → human approval |
| **Portfolio** | Manual entry, CSV import, read-only import from a public address; positions by source with P&L and weights |
| **Reports** | Daily, on-demand and trade-plan reports; filter by type and status; approve or reject; export to Markdown and PDF |
| **Scanner** | Top-N liquid coins (or your watchlist) ranked 0–100, liquidity floor, starred shortlist, "Build trade plan" |
| **Pipeline (trade plan)** | data → five parallel skills → timing agent → scenario stats → risk sizer → backtester → writer → verifier → human approval |
| **Trade-plan card** | Setup and status, price ladder (invalidation, entry zone, trigger, profit rule), size from max loss and the limit that binds, risk level, bull/base/bear with sample size and 95% intervals, backtest with overfitting warnings, tagged claims, "Paper trade this plan" |
| **Backtests** | In-sample, out-of-sample and walk-forward metrics after fees and slippage; out-of-sample equity vs buy and hold; folds, trades, warnings, assumptions |
| **Paper trading** | Simulated account: equity vs Bitcoin buy-and-hold, return, realised P&L, win rate, drawdown, pending/open/closed positions labelled by origin |
| **Settings** | Data mode and providers, agent mode and limits, mismatch tolerance, Polymarket toggle, trading preferences, theme, access mode |

![Coin detail](docs/images/coin-detail.png)
![Pipeline](docs/images/pipeline.png)
![Scanner](docs/images/scanner.png)
![Trade-plan card](docs/images/trade-plan.png)
![Paper trading](docs/images/paper.png)

---

## 3. Quick start with Docker

**Prerequisites:** Docker with Compose v2.24+. No API keys are needed.

```bash
git clone <this repository> lodestar && cd lodestar
make up                       # builds and starts db, redis, migrate+seed, api, worker, beat, web
open http://localhost:8080
```

`make up` runs `docker compose up --build -d`. A one-shot `migrate` container applies the database migrations and seeds first-run data, then the other services start. Every port is bound to `127.0.0.1` only.

Without keys Lodestar runs in **demo mode**. Every source returns deterministic synthetic data, a "Demo data" banner is shown, and the agents follow scripted tool plans. The seed creates:

- a watchlist (POL, BTC, ETH, SOL, LINK)
- demo holdings
- a verified report for each coin
- a market scan and trade plans for POL, ETH and LINK
- a clearly labelled demo paper-trading replay

The dashboard is populated straight away.

### A five-minute tour

1. Press **⌘K**, type `cardano` and select it. Lodestar tracks and watches the coin and opens its live pipeline run.
2. Watch the steps stream in. The run ends at **Human approval** with a verified report. Approve or reject it.
3. Open **Polygon (POL)** from the Overview for the full coin detail, or export any report to Markdown or PDF. [docs/POLYGON_SNAPSHOT.md](docs/POLYGON_SNAPSHOT.md) is an unedited export.
4. Open **Scanner**, run a scan and press **Build trade plan** on a shortlisted coin. The run ends with a verified trade-plan card. Approve it, then choose **Paper trade this plan**.
5. Open **Backtests** and **Paper trading** to see the stored backtests and the running paper performance.

Check a running stack end to end with `./scripts/smoke.sh` (`BASE_URL=http://127.0.0.1:8000` for the local dev API). CI runs the same script against the Docker stack.

### Live data and Claude agents

Copy `.env.example` to `.env`, set any of these, then run `make down && make up`.

| Variable | Effect |
|---|---|
| `LS_COINGECKO_API_KEY` (+ `LS_COINGECKO_PLAN=demo`) | Switches to **live** data from CoinGecko, Kraken, DefiLlama, Fear & Greed, RSS, Polymarket and public RPC. A free CoinGecko demo key is enough. `LS_DATA_MODE=live` forces live mode without a key, within public rate limits |
| `ANTHROPIC_API_KEY` | Analysts choose their own read-only tools with Claude (`claude-opus-5-5`, effort `medium`), and Claude writes the report. Numbers are still computed in code and every claim is still verified |
| `LS_AUTH_MODE=password` | Owner account with login (required when `LS_ENV=production`). The default `local` mode is single-user with no login, for a stack bound to localhost |

### Useful Docker commands

| Command | Does |
|---|---|
| `make ps` | Service status |
| `make logs` | Tail API, worker and beat logs |
| `make down` | Stop the stack (data volumes are kept) |
| `docker compose down -v` | Stop and **wipe** the database and Redis volumes |

---

## 4. Running without Docker (local development)

**Prerequisites:** Python 3.12 with [uv](https://docs.astral.sh/uv/), Node.js 20+, PostgreSQL 17 and Redis 7. You can run Postgres and Redis yourself or with `docker compose up -d db redis`.

```bash
make setup                         # uv sync + npm ci (+ git hooks once the folder is a git repo)
cp .env.example .env               # optional; defaults point at localhost Postgres/Redis
make migrate                       # alembic upgrade head
make seed                          # first-run data (idempotent)

# one terminal each:
make dev-api                       # FastAPI with reload → http://localhost:8000/docs
make dev-worker                    # Celery worker (runs pipelines, scans)
make dev-beat                      # optional: daily reports + hourly paper tick
make dev-web                       # Vite → http://localhost:5173
```

Expected defaults: database `postgresql+asyncpg://lodestar:lodestar@localhost:5432/lodestar` and Redis `redis://:lodestar@localhost:6379/0`. Change them with `LS_DATABASE_URL` and `LS_REDIS_URL`.

Handy commands that need no browser:

```bash
make run-pol                       # run the whole analysis pipeline for POL inline and print each step
make skill S=market-scanner        # any trader skill as JSON, no database or worker needed
make skill S=trade-plan ARGS="--coin solana"
make help                          # every Makefile target
```

**Notes for macOS:**

- The Makefile sets `PYTHONPATH=src` because `uv` can mark its editable-install `.pth` file as hidden, and Python then skips it. If you call `uv run` yourself from `backend/`, prefix it with `PYTHONPATH=src`.
- The Celery worker uses the `solo` pool, which avoids fork problems on macOS. It runs one async pipeline per process, so scale by running more workers.
- The Vite dev server proxies `/api` to `http://127.0.0.1:8000`. Set `LS_API_URL` to point it somewhere else.

---

## 5. Core ideas: evidence, claims, verifier, approval

Everything in Lodestar rests on four ideas. If you understand these, the rest of the code follows.

**1. Evidence.** Every number a report may mention is first registered by code as an evidence item with a namespaced id:

```
Evidence { id: "TEC-03", key: "macd_histogram", label: "MACD histogram (12/26/9)",
           value: -0.0012, unit: "usd", kind: "calculation", source: "lodestar",
           as_of: "...", inputs: ["DAT-14", "DAT-02"] }      # lineage back to raw data
```

`kind` is one of:

- `observation`: from a named provider
- `calculation`: from Lodestar code, with input lineage
- `text`: untrusted headlines and market questions

The prefix names the step that produced the item, so parallel agents never collide.

| Prefix | Producer | Prefix | Producer |
|---|---|---|---|
| `DAT` | Data step (prices, history, supply, liquidity) | `SCN` | Market scanner |
| `NWS` | Headlines | `EVT` | News/event scout |
| `PM` | Prediction markets | `LIQ` | Liquidity checker |
| `TEC` | Technical analyst | `TIM` | Timing agent |
| `FUN` | Fundamentals analyst | `SCE` | Scenario stats engine |
| `SEN` | Sentiment | `SIZ` | Risk and position sizer |
| `RSK` | Risk analyst | `BKT` | Backtester |
| `ASM` | Horizon assessments | `PF` | Your portfolio context |

**2. Claims.** A report is a list of short claims, each tagged and citing evidence:

```
Claim { text: "MACD histogram is negative.", tag: "interpretation", evidence_ids: ["TEC-03"] }
```

**3. Verifier.** Code checks every claim against the evidence it cites (see [6.6](#66-the-verifier)). It never edits anything. It passes the report, sends findings back to the writer, or fails the run.

**4. Human approval.** A verified report is saved as `pending_approval`. The pipeline pauses until you approve or reject it.

---

## 6. Architecture

### 6.1 System overview

```mermaid
flowchart LR
    U[You: browser] -->|HTTPS| W[web: nginx + React SPA]
    W -->|/api same-origin, SSE unbuffered| A[api: FastAPI]
    A --> P[(PostgreSQL<br/>users, assets, holdings, settings,<br/>runs, events, reports, scans,<br/>backtests, paper account,<br/>LangGraph checkpoints)]
    A --> R[(Redis<br/>cache, rate limits, refresh tokens,<br/>Celery broker, run event streams)]
    A -- send_task --> R
    R --> K[worker: Celery + LangGraph]
    B[beat: daily reports,<br/>hourly paper tick] --> R
    K --> P
    K -- XADD events --> R
    K --> EXT[CoinGecko · Kraken · DefiLlama ·<br/>alternative.me · RSS · Polymarket]
    A --> RPC[Public RPC / mempool.space<br/>wallet import]
    K --> LLM[Claude: optional]
```

| Process | Docker service | Port | Role |
|---|---|---|---|
| Web | `web` | 8080 | nginx serving the React build; proxies `/api` unbuffered for SSE |
| API | `api` | 8000 | FastAPI: REST, SSE, auth, exports. Starts runs by sending Celery tasks; never runs a pipeline itself |
| Worker | `worker` | – | Celery worker: runs the LangGraph pipelines, scans, the paper tick |
| Scheduler | `beat` | – | Celery beat: daily reports and the hourly paper-trading tick |
| Migrations | `migrate` | – | One-shot: `alembic upgrade head` and the first-run seed |
| Database | `db` | 5432 | PostgreSQL 17: the system of record and LangGraph checkpoints |
| Broker/cache | `redis` | 6379 | Redis 7: cache, rate limits, refresh tokens, Celery broker, event streams |

Locally, `make dev-web` serves the frontend on port 5173 instead of 8080.

### 6.2 Clean Architecture layers

The backend (`backend/src/lodestar/`) has four layers. **Dependencies point inward only.**

```mermaid
flowchart LR
    I[interfaces<br/>HTTP · Celery tasks · CLI · skills CLI] --> AP[application<br/>use cases · pipeline · ports]
    IN[infrastructure<br/>providers · LLM · LangGraph · DB · Redis · Celery] --> AP
    AP --> D[domain<br/>pure rules: indicators, scoring, risk,<br/>verification, trading maths]
    I --> IN
```

| Layer | Contains | May import |
|---|---|---|
| `domain/` | Entities, indicators, evidence and claims, scoring and risk, the verifier, reconciliation, portfolio maths, all trading maths. No I/O, no frameworks | Nothing from the project |
| `application/` | Use cases and services, the framework-free pipeline (nodes, ReAct loop, analysts, writer), trading skills and services, and `ports.py` (Protocols for every external dependency) | `domain` and its own ports |
| `infrastructure/` | Adapters implementing the ports: data providers (live and demo), Claude, the LangGraph engine, Postgres repositories, Redis cache and event bus, Celery, PDF export, security | `application`, `domain` |
| `interfaces/` | Delivery: FastAPI app and routers, Celery task entry points, CLI, skills CLI | Everything |

- **`infrastructure/container.py` is the composition root.** It is the only place that knows the concrete classes, and it wires adapters into use cases.
- **The pipeline nodes never import LangGraph.** The human-approval `interrupt` is injected as an `ApprovalGate`, and the graph wiring lives in `infrastructure/orchestration/langgraph_engine.py`. This keeps the agent logic testable without the framework.

How the SOLID principles map onto the code:

| Principle | In the code |
|---|---|
| Single responsibility | The data step collects; analysts analyse; the portfolio step synthesises; the writer explains; the verifier verifies |
| Open/closed | A new analyst is a new `Analyst` subclass plus one graph node; a new provider is a new adapter |
| Liskov | `ScriptedPolicy` / `ClaudeAnalystPolicy`, `TemplateReportWriter` / `ClaudeReportWriter`, and demo / live providers are interchangeable |
| Interface segregation | Small ports: `ExchangeProvider`, `ReferencePriceProvider`, `RunEventBus`, … |
| Dependency inversion | Use cases depend on `ports.py`; `container.py` wires the adapters |

### 6.3 Life of a request: adding a coin

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as API (FastAPI)
    participant DB as PostgreSQL
    participant R as Redis
    participant W as Worker (Celery + LangGraph)
    B->>A: POST /api/v1/assets {coingecko_id}
    A->>DB: track asset, add to watchlist, create run (queued)
    A->>R: send_task(run_pipeline, run_id)
    A-->>B: 201 {asset, run}
    B->>A: GET /api/v1/runs/{id}/events (SSE)
    R->>W: deliver task
    loop each step
        W->>DB: store event (seq n)
        W->>R: XADD ls:run:{id}:events
        R-->>A: new event
        A-->>B: SSE event
    end
    W->>DB: save verified report (pending_approval), checkpoint at interrupt
    B->>A: POST /api/v1/reports/{id}/approve
    A->>DB: record decision
    A->>R: send_task(resume_pipeline)
    R->>W: resume thread with the decision → run approved
```

The same flow serves trade plans (`POST /api/v1/trade-plans`). The run's `kind` selects the trade graph instead of the analysis graph.

### 6.4 The analysis pipeline

```mermaid
flowchart TD
    D["Data<br/>collect · sanitise · reconcile · register DAT/NWS/PM evidence"] --> T & F & S & R
    T["Technical (TEC)"] --> P
    F["Fundamental (FUN)"] --> P
    S["Sentiment (SEN)"] --> P
    R["Risk (RSK)"] --> P
    P["Portfolio (ASM, PF)<br/>synthesise both horizons · position context"] --> W
    W["Report writer"] --> V{"Verifier"}
    V -->|passed: save report, pending approval| H["Human approval<br/>(LangGraph interrupt)"]
    V -->|failed and repairs < 2| W
    V -->|failed after 2 repairs| X["Fail closed: run failed, nothing published"]
```

LangGraph compiles the graph with a **Postgres checkpointer**, keyed by run id.

- The four analysts run in the same super-step, so in parallel. Their writes to `evidence` and `analysts` use merge reducers.
- Graph state is plain JSON (`application/codec.py` encodes the market data), so any worker process can reload a checkpoint.

| Step | Does (all computation in code) | Evidence |
|---|---|---|
| **Data** | Required: snapshot and 365 days of history. Optional: exchange candles and ticker, reference price, supply, liquidity, Fear & Greed, chain TVL, headlines, prediction markets. Sanitises untrusted text, reconciles prices, registers evidence | `DAT`, `NWS`, `PM` |
| **Technical** | Trend vs 20/50/200-day averages, RSI, MACD, Bollinger, volatility, volume confirmation, support/resistance, 1-year trend | `TEC` |
| **Fundamental** | Size and rank, circulating ratio, FDV/market cap, turnover, liquidity depth and spreads, chain TVL | `FUN` |
| **Sentiment** | Fear & Greed extremes, headline counts, Polymarket odds (context only) | `SEN` |
| **Risk** | Itemised risk **per horizon**: volatility, drawdown, liquidity, size, dilution, sentiment extremes, recent move, price-source disagreement | `RSK` |
| **Portfolio** | Combines analyst signals into short-term and long-term scores, stances and confidence. Adds what you hold, its value, weight, P&L and concentration (no sizing advice) | `ASM`, `PF` |
| **Report writer** | Explains the bundle as tagged claims: a deterministic template, or Claude with structured output | – |
| **Verifier** | Checks every claim and the report: passes it, sends findings back, or fails closed | – |
| **Human approval** | Pauses the graph; the API records your decision and a worker resumes the thread | – |

Stances are `favorable` / `neutral` / `unfavorable`. Risk levels are `low` / `moderate` / `high` / `very_high`. Short term means days to about four weeks; long term means six months and beyond.

### 6.5 Analysts: ReAct loops with read-only tools

Each analyst runs the loop in `application/pipeline/react.py`:

```
for step in 1..max_steps (default 6):
    action = policy.decide(brief, tool specs, history)     # Claude or scripted
    if action is FinalAnswer: stop
    results = toolkit.execute(calls)                        # read-only, validated arguments
    emit tool_call events (args, observation, evidence ids)
else: stop_reason = "step_limit"
finalize(): compute required metrics + signals in code (idempotent)
claims: model claims pre-screened by the verifier rules; invalid ones dropped; none left -> template claims
```

- **Tools are read-only.** They compute over data already collected for the run and register their results as evidence. Examples: `compute_indicator(name, window)`, `price_summary(days)`, `supply_profile`, `market_structure`, `fear_greed`, `headlines`, `assess_horizon_risk(horizon)`, `reconciliation_status`, `list_evidence`. Tools cannot fetch, write or trade, and their arguments are schema-validated.
- **The loop belongs to the code.** The model only chooses the next action. The step limit, the tool set and the final computations are code. If the model stops early, loops or is unavailable, the analyst's signals are still computed and deterministic claims are used instead.
- **Scripted policy.** Without an Anthropic key, each analyst follows a fixed tool plan. Demo runs therefore still show real ReAct steps in the timeline.

### 6.6 The verifier

The verifier lives in `domain/verification.py` and, for trade plans, `domain/trading/plan.py`.

| Rule | Rejects |
|---|---|
| C1 | Cited ids that do not exist |
| C2 | A non-assumption claim with no citation |
| C3 | A `fact` without a provider observation; a `calculation` without a computed item |
| C4 | Any number that doesn't match a cited evidence value (rounding-aware; ratios may be written as percentages; indicator parameters and years are ignored) |
| C5 | Certainty, guarantee or promotional language |
| C6 | Price targets and buy/sell/hold instructions |
| C7 | A `scenario` that is not conditional ("if", "could", "would"…) |
| C8 | A claim that cites a stance or risk-level item without stating its value |
| C9 | Empty or overlong claims; too many claims |
| R1–R3 | Analysis reports: missing headline or horizon section; missing short- or long-term assessment or risk level; missing or altered disclaimer |
| P1 | Trade plans: timing must cite the computed entry zone, trigger and invalidation |
| P2 | Timing stated as a "best time" instead of a set of conditions |
| P3 | A bull/base/bear scenario not cited, or a small sample not stated as such |
| P4 | A size that doesn't cite units, notional and max loss, or a loss at the stop larger than the max loss |
| P5 | The computed risk level not cited |
| P6 | Missing headline or invalidation statement |
| P7 | Missing or altered trading disclaimer |

Each finding names its location, for example `short_term.watch[0]`, and the findings go back to the writer. After `LS_MAX_REPAIRS` (default 2) failed repairs, the run fails closed and nothing is published.

### 6.7 Human approval and resume

1. The verifier passes. The report is saved as `pending_approval`, the run becomes `awaiting_approval`, and the approval node calls LangGraph `interrupt()`, which saves a checkpoint.
2. You approve or reject in the UI. The API records the decision immediately (idempotent) and enqueues `resume_pipeline`.
3. A worker resumes the thread with `Command(resume=decision)`. The approval node re-applies the decision idempotently and the graph ends.

Run statuses: `queued` → `running` → `awaiting_approval` → `approved` | `rejected`, or `failed`.

### 6.8 Live streaming (SSE)

1. **Storing.** `RunEventRecorder` writes every event to the `pipeline_events` table. The database allocates sequence numbers atomically, using a savepoint and retry, because both the API and the worker write to the same run.
2. **Publishing.** Each event is then published to a Redis Stream (`ls:run:<id>:events`, capped, 24 h TTL).
3. **Serving.** `GET /runs/{id}/events` first replays stored events after `Last-Event-ID`. It then tails the stream, sends heartbeats, catches up from the database when idle, and closes once the run reaches a resting status.
4. **Reading.** The browser uses a fetch-based SSE reader (`frontend/src/lib/sse.ts`). It can send an `Authorization` header and reconnects with `Last-Event-ID`. nginx proxies `/api` unbuffered.

Event shape: `{run_id, seq, ts, step, type: run|step|tool_call|note, status, payload: {inputs, outputs, evidence_ids, duration_ms, attempt, tool, args, observation, message}}`. Payloads are size-bounded.

### 6.9 Trader Skills (paper trading only)

A second graph, built by `build_trade_graph` from `TradeNodes`, runs when a run's kind is `trade_plan`. `TradeNodes` is a subclass of the analysis nodes. Both graphs share the checkpointer, the event recorder, the approval interrupt and the repair/fail-closed routing.

```mermaid
flowchart TD
    SC[Scanner: top-N liquid coins] --> SL[Shortlist] -->|select a coin| D
    D["Data (+ order book, funding, chain fees, 720d bars, BTC closes, scanner metrics)"] --> TA & FA & SE & NE & LQ
    TA["Technical analyst (TEC)"] --> TI
    FA["Fundamentals analyst (FUN)"] --> TI
    SE["Sentiment reader (SEN)"] --> TI
    NE["News/event scout (EVT)"] --> TI
    LQ["Liquidity checker (LIQ)"] --> TI
    TI["Timing agent (TIM)<br/>setup, entry zone, trigger, invalidation"] --> SS["Scenario stats engine (SCE)<br/>bull/base/bear, n, 95% intervals"]
    SS --> RS["Risk and position sizer (SIZ)<br/>max loss → caps"] --> BT["Backtester (BKT)<br/>IS / OOS / walk-forward, saved"]
    BT --> W["Trade-plan writer"] --> V{"Verifier C1–C9 + P1–P7"}
    V -->|passed| H["Human approval"] --> PP["Paper trade (optional)"]
    V -->|failed, repairs < 2| W
    V -->|failed after 2 repairs| X["Fail closed"]
```

#### The eleven skills

| Skill | Computes (in code) |
|---|---|
| market-scanner | Score = trend (40) + breakout (20) + volume spike (20) + relative strength vs BTC (20); liquidity floor; top-5 shortlist |
| news-event-scout | Headlines and event categories: unlocks, listings, upgrades, regulation, security |
| sentiment-reader | Fear & Greed, headline flow, perpetual funding rate, Polymarket odds |
| fundamentals-analyst | Market cap, FDV dilution, TVL, chain fees and revenue (DefiLlama) |
| technical-analyst | Moving averages, RSI, MACD, Bollinger, volatility, support/resistance |
| liquidity-checker | Spread, depth within 2%, slippage for $1k–$250k from walking the order book |
| timing-agent | Setup (breakout, pullback, trend reclaim): **entry zone, trigger, invalidation**; never "the best time" |
| scenario-stats-engine | Bull/base/bear from non-overlapping historical analogs: win rate, mean, median, max drawdown, **sample size, 95% intervals**, and an explicit "too small to trust" flag |
| risk-position-sizer | Size from max loss and stop distance, capped by concentration, order-book slippage and correlation; risk level |
| backtester-paper-trader | Next-open fills (no look-ahead), fees and slippage, 70/30 out-of-sample split, walk-forward folds, overfitting warnings; the paper engine applies the same rules to new daily bars |
| report-verifier | Claim rules C1–C9 plus trade-plan rules P1–P7 |

#### The maths (pure code in `domain/trading/`)

| Module | Rules |
|---|---|
| `bars.py` | Daily OHLCV bars (exchange candles, or approximated from closes and flagged), Wilder ATR, rolling means |
| `setups.py` | Signals on the close of bar *i* use only bars ≤ *i*. Levels: entry zone = trigger → trigger + 0.5 ATR, invalidation = trigger − 2 ATR, profit rule at 2R. Status is active, extended or waiting |
| `stats.py` | Historical analogs entered at the next open, net of costs. Wilson intervals for rates, t intervals for means. Reliability: under 10 cases is *insufficient*, under 30 is *small*. Bull/base/bear are split at ±0.5 σ of the horizon return |
| `backtest.py` | Simulator: the stop is checked before the profit rule, plus a time exit, with fees and slippage on both sides. A 3 × 3 parameter grid is fitted on the first 70% of history and judged out-of-sample on the rest. Walk-forward: train 240 days, test 60. Overfitting warnings |
| `sizing.py` | Units = max loss ÷ (entry − stop + costs), then capped by the max position %, the order-book slippage limit and correlation with open paper positions. Reports which limit binds |
| `paper.py` | The paper state machine (below), with the same fill rules as the backtester |
| `scanner.py` | The transparent 0–100 score and the liquidity floor |
| `plan.py` | The trade-plan draft and verifier rules P1–P7 |

#### Paper position lifecycle

```mermaid
stateDiagram-v2
    [*] --> pending: opened from an approved trade plan
    pending --> triggered: daily close above the trigger
    triggered --> open: fills at the next open
    triggered --> cancelled: gaps more than 2% above the zone
    pending --> cancelled: expiry or manual cancel
    open --> closed: stop, profit rule or time limit
    closed --> [*]
    cancelled --> [*]
```

**Trading services** live in `application/trading/services.py`:

- **`ScanService`** runs the Celery task `run_scan`. It ranks liquid coins first and marks a top-5 shortlist.
- **`BacktestService`** saves every backtest, whether manual or from a plan.
- **`PaperService`**:
  - Opens positions only from approved trade plans.
  - Processes completed daily bars up to yesterday on an hourly beat, and books fees and cash.
  - Benchmarks against Bitcoin buy-and-hold.
  - In demo mode, a labelled "demo replay" starts the account in the past so the screen has history.

### 6.10 Data sources and demo mode

| Source | Used for | Demo equivalent |
|---|---|---|
| CoinGecko | Snapshot, 365-day history, supply, liquidity (tickers with depth), search, top-N universe | `DemoMarketData` (seeded random walk anchored to a fixed price) |
| Kraken (public endpoints) | Daily OHLC candles, ticker (second price feed), order book, futures funding | `DemoExchange` |
| DefiLlama | Chain TVL, fees and revenue; `coins.llama.fi` reference price (third feed) | `DemoOnChain`, `DemoReferencePrice` |
| alternative.me | Fear & Greed index | `DemoSentiment` |
| RSS (CoinDesk, Cointelegraph, Decrypt) | Headlines (untrusted context) | `DemoNews` |
| Polymarket Gamma (optional) | Crowd odds mentioning the asset | `DemoPredictions` |
| Public JSON-RPC, mempool.space | Read-only wallet balances | `DemoWallets` |

- **Reconciliation.**
  - Price is compared across the primary feed, the exchange and the aggregator, each against the median of the three.
  - A deviation beyond the tolerance (1.5% by default, adjustable per user) marks the run `mismatch`. It also adds a `data_disagreement` risk factor and appears in the timeline and the Data-quality card.
  - In demo mode Chainlink carries a deliberate 3.3% gap so you can see this.
- **Demo mode.**
  - It is selected automatically when no CoinGecko key is set (`LS_DATA_MODE=auto`).
  - Every demo source is named `demo*` in the evidence, the UI shows a banner, and exports are stamped "DEMO DATA".

### 6.11 Claude integration

- **Analyst policy** (`ClaudeAnalystPolicy`). A manual tool-use loop on `messages.create` with the analyst's tools plus `submit_findings`. At the step limit the model is told to submit. Defaults: model `claude-opus-5-5`, effort `medium`.
- **Writer** (`ClaudeReportWriter`). Uses `messages.parse` with a Pydantic schema, so the output always parses. Code attaches the disclaimer. Repair attempts include the verifier's findings.
- **Shared by both.**
  - Static, cache-controlled system prompts.
  - Server-side refusal fallbacks.
  - Any API failure becomes `LlmUnavailable`. The writer then falls back to the deterministic writer, and the verifier checks either way.
- **Prompt injection.**
  - Headlines and market questions are normalised, stripped of control and bidi characters, screened for injection phrasing, JSON-fenced and labelled untrusted.
  - Tools are read-only, so an injection can at most change wording, and wording is verified.
- **No fine-tuning.** The task is explaining structured data. Hallucination is a grounding problem, and the evidence bundle and the verifier solve it.

Prompts live in `infrastructure/llm/prompts.py` with a `PROMPT_VERSION`.

### 6.12 Background jobs

| Celery task (`lodestar.*`) | Trigger | Does |
|---|---|---|
| `run_pipeline` | API (`POST /assets`, `/assets/{id}/runs`, `/trade-plans`) | Executes an analysis or trade-plan graph for one run |
| `resume_pipeline` | API (approve/reject) | Resumes the paused graph with your decision |
| `daily_reports` | Beat, daily at `LS_DAILY_REPORT_HOUR_UTC`:00 (default 06:00 UTC) | Queues a report for every watchlisted coin |
| `run_scan` | API (`POST /scans`) | Scores the universe and stores a ranked shortlist |
| `paper_tick` | Beat, hourly at minute 10; or "Process new bars" | Applies every completed daily bar to open paper positions |

Rules that keep runs safe:

- **One active run per asset.** A second request returns the run already in flight unless it is forced.
- **Lost tasks.** A run queued or running for more than 15 minutes is treated as lost and expired on the next request.
- **Idempotent tasks.** Tasks skip runs that are no longer `queued`, task ids are derived from run ids, and `acks_late` is set.

### 6.13 Data model

```mermaid
erDiagram
    users ||--o{ watchlist_items : has
    users ||--o{ holdings : owns
    users ||--o| user_settings : has
    assets ||--o{ holdings : of
    assets ||--o{ pipeline_runs : about
    pipeline_runs ||--o{ pipeline_events : emits
    pipeline_runs ||--o| reports : produces
    users ||--o{ scans : runs
    users ||--o| paper_accounts : has
    paper_accounts ||--o{ paper_positions : holds
    paper_accounts ||--o{ paper_equity : tracks
    reports ||--o| paper_positions : "approved plan"
    assets ||--o{ backtests : of
    holdings { uuid id PK; uuid user_id FK; uuid asset_id FK; text source "manual|csv|wallet:chain:address"; numeric quantity; numeric avg_cost_usd; text notes_encrypted }
    pipeline_runs { uuid id PK; uuid asset_id FK; text kind; text status; text current_step; int repair_count; text error; text data_mode; text llm_mode }
    pipeline_events { bigint id PK; uuid run_id FK; int seq "unique per run"; text step; text type; text status; jsonb payload }
    reports { uuid id PK; uuid run_id UK; text kind "daily|on_demand|trade_plan"; text status "pending_approval|approved|rejected"; text headline; text setup_kind; text setup_status; jsonb content; timestamptz decided_at }
    scans { uuid id PK; text universe; int top_n; text status; int progress; jsonb results }
    backtests { uuid id PK; uuid asset_id FK; uuid run_id; text kind; jsonb config; jsonb summary; jsonb result }
    paper_positions { uuid id PK; uuid report_id FK; text origin "plan|demo_replay"; text status; numeric trigger; numeric stop; numeric units; numeric pnl_usd }
```

- **Migrations** live in `backend/alembic/versions/`:
  - `0001_initial`
  - `0002_agentic_pipeline`
  - `0003_trader_skills`
- **Checkpoint tables.** LangGraph's saver manages its own `checkpoint*` tables, so they are excluded from Alembic.
- **Reports** are immutable JSONB snapshots. Each holds the assessments, draft, full evidence bundle, reconciliation, verification result and pipeline version.
- **Holdings** are unique per (user, asset, source), so the same coin from a wallet and from manual entry are separate lots.

### 6.14 Reliability

| Concern | Approach |
|---|---|
| Upstream limits and latency | Redis cache per data type; per-host circuit breakers; retries with jitter that honour `Retry-After`; 20 s per-source timeouts |
| Partial outages | A missing optional source becomes a data gap; missing core data fails the run with a clear error |
| Model outages | Analysts and writer degrade to deterministic implementations; verification is unchanged |
| Lost tasks | Stale-run expiry, idempotent tasks, `acks_late` |
| Live updates | Redis Streams with database catch-up, heartbeats and resumable SSE |
| Observability | structlog JSON logs with request ids, Prometheus `/metrics`, health probes, per-call LLM token and cache logs, a full event audit trail per run |

### 6.15 Technology choices

| Layer | Choice | Why |
|---|---|---|
| API | Python 3.12, FastAPI, Pydantic v2, SSE | Async I/O, typed schemas, OpenAPI docs at `/docs` |
| Agents | LangGraph, with our own ReAct loop inside each analyst node; Claude via the official `anthropic` SDK | Parallel fan-out, conditional repair loop, durable checkpoints and `interrupt` across processes. The step limit, tool validation and evidence registration stay ours and testable without a model |
| Jobs | Celery (Redis broker) worker + beat | Mature retries and acks, a scheduler, and the API only `send_task`s by name |
| Data | PostgreSQL 17 (SQLAlchemy 2 async, Alembic), Redis 7 | One relational source of truth; Redis Streams keep history so late SSE subscribers can replay |
| Exchange | Kraken public endpoints | OHLC, ticker and order book without a key, in more regions than Binance |
| PDF | fpdf2 | Pure Python, no system libraries in the slim image |
| Web | React 19, TypeScript, Vite, TanStack Query, React Router, Tailwind v4, Lightweight Charts | Fast dev loop, cached server state, financial charts |
| Quality | ruff, mypy --strict, pytest, ESLint, Vitest, pip-audit, npm audit, gitleaks, Trivy | See [section 11](#11-testing-and-quality) |

---

## 7. Folder structure

```
lodestar/
├── README.md                     ← you are here
├── CONTRIBUTING.md               workflow, coding standards, testing strategy
├── Makefile                      every command: setup, up, dev-*, migrate, seed, skill, test, lint, check
├── docker-compose.yml            db, redis, migrate, api, worker, beat, web (ports on 127.0.0.1)
├── .env.example                  all settings with comments (copy to .env)
├── .pre-commit-config.yaml       ruff, gitleaks and friends before each commit
├── .editorconfig
├── .github/
│   ├── workflows/ci.yml          lint, types, tests, audits, Docker stack + smoke test, Trivy
│   ├── workflows/release.yml     vX.Y.Z tag → images to GHCR with SBOM and provenance
│   ├── dependabot.yml
│   └── pull_request_template.md
│
├── backend/
│   ├── Dockerfile                one image for api, worker, beat and migrate
│   ├── pyproject.toml, uv.lock   dependencies and tool config (ruff, mypy, pytest, coverage)
│   ├── alembic.ini
│   ├── alembic/versions/         0001_initial · 0002_agentic_pipeline · 0003_trader_skills
│   ├── src/lodestar/
│   │   ├── config.py             typed settings (LS_* env vars), production safety checks
│   │   │
│   │   ├── domain/               PURE RULES: no I/O, no frameworks
│   │   │   ├── models.py             entities and enums (Asset, Candle, RunStatus, Stance, RiskLevel…)
│   │   │   ├── indicators.py         SMA, EMA, RSI, MACD, Bollinger, volatility, drawdown
│   │   │   ├── evidence.py           Evidence, EvidenceRegistry (namespaced ids), EvidenceBundle
│   │   │   ├── claims.py             Claim + ClaimTag
│   │   │   ├── scoring.py            analyst signal rules, per-horizon risk model, synthesis
│   │   │   ├── report.py             ReportDraft, DISCLAIMER
│   │   │   ├── verification.py       the verifier: claim rules C1–C9, report rules R1–R3
│   │   │   ├── reconciliation.py     cross-provider price reconciliation
│   │   │   ├── portfolio.py          weights, concentration (HHI), blended risk, volatility
│   │   │   ├── addresses.py          public-address validation, private-key / seed-phrase detection
│   │   │   ├── errors.py             domain errors (mapped to HTTP problem responses)
│   │   │   └── trading/              bars, setups, stats, backtest, sizing, paper, scanner, plan (P1–P7)
│   │   │
│   │   ├── application/          USE CASES: depend on domain + ports only
│   │   │   ├── ports.py              Protocols for providers, repositories, queue, workflow engine, event bus…
│   │   │   ├── pipeline/             the framework-free analysis pipeline
│   │   │   │   ├── nodes.py              graph steps, instrumentation, repair routing
│   │   │   │   ├── react.py              ReAct loop, Toolkit, ScriptedPolicy
│   │   │   │   ├── analysts/             base, technical, fundamental, sentiment, risk
│   │   │   │   ├── data_step.py          collect, sanitise, reconcile, register evidence
│   │   │   │   ├── portfolio_step.py     horizon synthesis + position context
│   │   │   │   ├── writer.py             ReportWriter port + deterministic writer
│   │   │   │   ├── approval.py, events.py, state.py, formatting.py
│   │   │   ├── trading/              Trader Skills
│   │   │   │   ├── analysts.py           the five parallel skills (incl. news/event scout, liquidity)
│   │   │   │   ├── engines.py            timing, scenario stats, sizing, backtest steps
│   │   │   │   ├── nodes.py              TradeNodes (trade-graph steps)
│   │   │   │   ├── writer.py             deterministic trade-plan writer
│   │   │   │   ├── coordinator.py        whole flow in-process (used by the skills CLI)
│   │   │   │   ├── services.py           ScanService, BacktestService, PaperService
│   │   │   │   └── common.py
│   │   │   ├── services/             assets, runs, reports, portfolio, overview, settings
│   │   │   ├── exports.py            Markdown outlines for reports and trade plans
│   │   │   ├── importers.py          CSV and public-address import
│   │   │   ├── auth.py, codec.py, sanitize.py, serialization.py
│   │   │
│   │   ├── infrastructure/       ADAPTERS implementing the ports
│   │   │   ├── container.py          composition root (the only place that builds concrete classes)
│   │   │   ├── providers/            coingecko, kraken, defillama, sentiment, news, polymarket, wallets, demo
│   │   │   ├── llm/                  Claude analyst policy + writer, prompts
│   │   │   ├── orchestration/        LangGraph graphs (analysis + trade), engine, Postgres checkpointer
│   │   │   ├── queue/celery_app.py   Celery app, beat schedule, JobQueue adapter
│   │   │   ├── events/bus.py         Redis Streams event bus (+ in-memory for tests)
│   │   │   ├── db/                   SQLAlchemy models + repositories
│   │   │   ├── cache/                Redis JSON cache
│   │   │   ├── export/pdf.py         PDF export (fpdf2)
│   │   │   ├── security/             passwords (Argon2id), JWT tokens, field encryption, rate limits
│   │   │   ├── observability/        structured logging
│   │   │   └── http.py               shared HTTP client: retries, circuit breakers, timeouts
│   │   │
│   │   └── interfaces/           DELIVERY
│   │       ├── http/                 FastAPI app, routers (assets, runs, reports, me, trading, auth, health),
│   │       │                         schemas, deps, middleware, problem+json errors
│   │       ├── workers/tasks.py      Celery tasks: run, resume, daily, scan, paper tick
│   │       ├── cli.py                seed · run <coin> · daily
│   │       └── skills.py             run any trader skill and print JSON (no DB)
│   └── tests/
│       ├── fakes.py              in-memory repositories, queue, clock, LLM fakes
│       ├── unit/                 indicators, domain, verifier, ReAct + importers, trading maths
│       └── integration/          API journeys, pipeline graph, trading, LLM adapters, live adapters, Postgres
│
├── frontend/
│   ├── Dockerfile, nginx.conf    production build served by nginx (SSE unbuffered, strict CSP)
│   ├── package.json, vite.config.ts, tsconfig.json, eslint.config.js, index.html
│   └── src/
│       ├── main.tsx, App.tsx     entry point and routes
│       ├── index.css             design tokens (light/dark), validated chart palette
│       ├── api/
│       │   ├── client.ts             fetch wrapper, auth token, problem+json errors
│       │   ├── hooks.ts              every TanStack Query hook (the only way to fetch data)
│       │   └── types.ts              API types (Report = AnalysisReport | TradePlanReport)
│       ├── components/
│       │   ├── Layout.tsx            navigation, demo banner, theme
│       │   ├── AssetSearch.tsx       ⌘K coin search
│       │   ├── CandleChart.tsx       candles + SMA/Bollinger + RSI panel
│       │   ├── CompareChart.tsx      two series on one axis (backtest, paper equity)
│       │   ├── AllocationBar.tsx     segmented allocation bar
│       │   ├── Timeline.tsx          live pipeline timeline
│       │   ├── ReportView.tsx        analysis report, claims, evidence, approval bar
│       │   ├── TradePlanView.tsx     trade-plan card: ladder, sizing, scenarios, backtest
│       │   └── ui.tsx                Card, Button, StatTile, Meter, badges…
│       ├── lib/
│       │   ├── sse.ts                fetch-based SSE reader with resume
│       │   ├── pipeline.ts           event → timeline reducer, step layouts per run kind
│       │   ├── trading.ts            setup labels, price-ladder scale
│       │   ├── format.ts             number, price and date formatting
│       │   └── *.test.ts             Vitest unit tests
│       └── pages/                Overview, Coin, Pipeline, Portfolio, Reports, Scanner,
│                                 Backtests, Paper, Settings, Login
│
├── skills/                       11 trader skills + trade-plan coordinator as Claude skills
│   ├── README.md
│   └── <skill-name>/SKILL.md
├── scripts/smoke.sh              end-to-end acceptance test against a running stack
└── docs/
    ├── ARCHITECTURE.md           the architecture in more depth
    ├── SECURITY.md               threat model and controls
    ├── UI.md                     screen layouts and chart rules
    ├── ROADMAP.md                done, next, later; deployment path
    ├── POLYGON_SNAPSHOT.md       unedited example report export
    └── images/                   screenshots used in this README
```

---

## 8. HTTP API

All endpoints are under `/api/v1` unless noted. Interactive OpenAPI docs are at `http://localhost:8000/docs` (disabled in production). Errors use RFC 9457 `application/problem+json`. Endpoints marked *owner* change data and require the owner role in password mode.

| Area | Endpoints |
|---|---|
| Health (no prefix) | `GET /health/live` · `GET /health/ready` · `GET /metrics` (internal only) |
| Auth | `POST /auth/register` · `POST /auth/login` · `POST /auth/refresh` · `POST /auth/logout` · `GET /auth/me` |
| Session and overview | `GET /session` · `GET /overview` |
| Assets and watchlist | `GET /assets/search?q=` · `POST /assets` *(track, watch, start a run)* · `GET /assets` · `GET /assets/{id}` · `GET /assets/{id}/chart` · `GET /assets/{id}/report` · `POST /assets/{id}/runs?force=` · `GET /watchlist` · `PUT /watchlist/{id}` · `DELETE /watchlist/{id}` |
| Pipeline runs | `GET /runs` · `GET /runs/{id}` · `GET /runs/{id}/events` *(SSE, supports `Last-Event-ID`)* |
| Reports | `GET /reports` · `GET /reports/{id}` · `POST /reports/{id}/approve` · `POST /reports/{id}/reject` · `GET /reports/{id}/export.md` · `GET /reports/{id}/export.pdf` |
| Portfolio | `GET /portfolio` · `PUT /portfolio/holdings` · `DELETE /portfolio/holdings/{id}` · `POST /portfolio/import/csv` · `POST /portfolio/import/address` |
| Settings | `GET /settings` · `PUT /settings` |
| Scanner | `POST /scans` · `GET /scans` · `GET /scans/latest` · `GET /scans/{id}` |
| Trade plans | `POST /trade-plans` *(starts a trade-plan run)* |
| Backtests | `POST /backtests` · `GET /backtests` · `GET /backtests/{id}` |
| Paper trading | `GET /paper` · `POST /paper/positions` *(approved plans only)* · `POST /paper/positions/{id}/cancel` · `POST /paper/tick` · `POST /paper/reset` · `POST /paper/demo-replay` |

Rate limits: 120 requests/min, 5 logins/min per IP, 30 analyses (runs, scans, trade plans, backtests) per hour.

---

## 9. Trader Skills as Claude skills

Each skill in [`skills/`](skills/README.md) is packaged as a Claude skill (`skills/<name>/SKILL.md`). Each one calls the same code as the app through a CLI that needs no database or worker and prints JSON:

```bash
make skill S=market-scanner ARGS="--top-n 20"
make skill S=timing-agent ARGS="--coin ethereum"
make skill S=risk-position-sizer ARGS="--coin solana --account 10000 --max-loss-pct 1"
make skill S=trade-plan ARGS="--coin solana" > plan.json
make skill S=report-verifier ARGS="--file plan.json"     # exits 1 if verification fails
```

Options: `--coin`, `--top-n`, `--account`, `--max-loss-pct`, `--horizon`, `--fee-bps`, `--slippage-bps`, `--min-volume-usd`, `--file`. Set `LS_DATA_MODE=demo` to run offline.

To use them in Claude Code, copy or symlink the folders into `.claude/skills/` (project) or `~/.claude/skills/` (personal). Every `SKILL.md` carries the same rules as the verifier:

- numbers only from the output
- claims tagged with evidence ids
- no targets and no "best time"
- small samples stated
- paper only
- the disclaimer unchanged

---

## 10. Configuration

All settings are environment variables prefixed `LS_` (plus `ANTHROPIC_API_KEY`). The full commented list is in [.env.example](.env.example), and the typed definitions are in `backend/src/lodestar/config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `LS_ENV` | `local` | `local` · `test` · `staging` · `production` (production enforces password auth, strong secrets, HSTS, no `/docs`) |
| `LS_DATABASE_URL` | `postgresql+asyncpg://lodestar:lodestar@localhost:5432/lodestar` | Postgres connection |
| `LS_REDIS_URL` | `redis://localhost:6379/0` | Redis (cache, streams, broker unless `LS_CELERY_BROKER_URL` is set) |
| `LS_AUTH_MODE` | `local` | `local` (single user, no login, localhost only) or `password` |
| `LS_JWT_SECRET` | dev value | Required in password mode; `make secrets` prints one |
| `LS_FIELD_ENCRYPTION_KEYS` | empty | Fernet keys for holding notes; first encrypts, all decrypt |
| `LS_ALLOW_REGISTRATION` | `false` | After the first (owner) account, registration is closed |
| `LS_CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed browser origins (JSON list) |
| `LS_DATA_MODE` | `auto` | `auto` = live if a CoinGecko key is set, else demo; `demo`; `live` |
| `LS_COINGECKO_API_KEY` / `LS_COINGECKO_PLAN` | – / `public` | Live market data; `demo` plan for a free key |
| `LS_RPC_URLS` | public nodes | JSON map of chain → RPC URL for wallet import |
| `ANTHROPIC_API_KEY` | – | Enables Claude analysts and writer |
| `LS_LLM_ENABLED` | `true` | Turn Claude off even when a key is set |
| `LS_LLM_MODEL` / `LS_LLM_EFFORT` | `claude-opus-5-5` / `medium` | Agent model and reasoning effort |
| `LS_MAX_AGENT_STEPS` | `6` | ReAct step limit per analyst (2–12) |
| `LS_MAX_REPAIRS` | `2` | Verifier repair loops before failing closed (0–2) |
| `LS_MISMATCH_TOLERANCE_PCT` | `1.5` | Default price-disagreement threshold (per-user override in Settings) |
| `LS_DAILY_REPORT_HOUR_UTC` | `6` | Hour for daily reports |
| `LS_DEMO_STEP_DELAY_MS` | `350` | Demo only: paces steps so the live timeline is watchable |
| `LS_RATE_LIMIT_PER_MINUTE` / `LS_LOGIN_ATTEMPTS_PER_MINUTE` / `LS_ANALYSES_PER_HOUR` | `120` / `5` / `30` | Rate limits |

**Per-user preferences** are edited in **Settings** and stored in the database, not in the environment:

- Polymarket toggle, mismatch tolerance and theme.
- Trading preferences:

| Preference | Default |
|---|---|
| Max loss per trade | 1% |
| Max position | 25% |
| Max slippage | 0.5% |
| Fees per side | 10 bps |
| Slippage per side | 5 bps |
| Horizon | 14 days |
| Liquidity floor (24 h volume) | $5M |
| Paper starting cash | $10,000 |

---

## 11. Testing and quality

```bash
make check     # everything CI runs except Docker: ruff, mypy --strict, pytest + coverage, ESLint, tsc, Vitest
make test      # backend pytest (with coverage) + frontend Vitest
make lint      # ruff check + format check + mypy; ESLint + tsc
make format    # auto-fix and format
LS_TEST_DATABASE_URL=postgresql+asyncpg://lodestar:lodestar@localhost:5432/lodestar_test make test-pg
./scripts/smoke.sh   # acceptance test against the Docker stack (http://localhost:8080)
BASE_URL=http://127.0.0.1:8000 ./scripts/smoke.sh   # same, against the local dev API
```

| Level | What | Where |
|---|---|---|
| Unit | Indicators, scoring and risk, every verifier rule, reconciliation, portfolio maths, address safety, ReAct limits, CSV parsing, trading maths (setups without look-ahead, intervals, sizing caps, backtest splits, paper state machine) | `backend/tests/unit/` |
| Pipeline graph | LangGraph end to end over demo data: parallel analysts, repair loop, fail closed, approval resume, model outage, price mismatch, stale runs | `tests/integration/test_pipeline.py` |
| API journeys | HTTP flows per screen over in-memory adapters, SSE replay/resume, exports, imports, both auth modes | `tests/integration/test_api.py` |
| Trading | Scanner shortlist, verified trade-plan card, exports, backtests, paper trading (refused before approval, fills on new bars), demo replay, skills CLI, every skill packaged | `tests/integration/test_trading.py` |
| Adapters | Claude policy and writer against a fake Messages API; live providers against `httpx.MockTransport` | `test_llm_adapters.py`, `test_live_adapters.py` |
| Database | Repositories against real Postgres (CI service container) | `test_postgres_repositories.py` |
| Frontend | Formatting, SSE parser, timeline reducer, trading helpers (Vitest) | `frontend/src/**/*.test.ts` |
| Stack smoke | Dashboard, POL report, add coin → verified report, exports, scanner → trade plan → backtest → paper position | `scripts/smoke.sh` |

The test rules:

- No test touches the network. Tests use `tests/fakes.py`, the demo providers or `httpx.MockTransport`.
- Backend coverage must stay at 80% or more.
- Every bug fix gets a regression test.
- Every verifier rule has a positive and a negative case.

---

## 12. CI/CD

**CI** is defined in `.github/workflows/ci.yml` and runs on every push and pull request.

| Job | Steps |
|---|---|
| backend | ruff lint and format; `mypy --strict`; migrations apply and `alembic check` matches the models; pytest with the 80% coverage gate, including Postgres repository tests; `pip-audit` |
| frontend | ESLint; `tsc`; Vitest; production build; `npm audit` |
| secrets-scan | gitleaks |
| stack | builds the Docker images; starts the stack with no keys (demo mode); runs `scripts/smoke.sh`; Trivy image scan |

**Release** is defined in `release.yml`. Pushing a `vX.Y.Z` tag publishes the backend and frontend images to GHCR with an SBOM and provenance.

---

## 13. Security

Lodestar holds information about your money, so it is built as if it were exposed to the internet, even on a laptop. Summary:

- **Read-only.**
  - No private keys, no signing, no orders.
  - Wallet import accepts public addresses only.
  - Anything shaped like a private key or seed phrase is rejected before it is stored, logged or sent.
- **Paper only.** Kraken is used through public market-data endpoints only. Paper positions open only from a trade plan a human approved.
- **Access.**
  - `local` mode has no login and is only for a localhost-bound stack.
  - `password` mode uses Argon2id and a 15-minute in-memory access JWT.
  - The refresh token is a rotating, single-use `HttpOnly; SameSite=Strict` cookie.
  - Production refuses to start without password mode and strong secrets.
- **Input and output.**
  - Pydantic schemas forbid extra fields.
  - Body and import size caps; parameterised SQL only; `defusedxml` for RSS.
  - Fixed provider URLs prevent SSRF.
  - Strict CSP and security headers.
- **Secrets.**
  - `SecretStr` settings with log redaction; `.env` is git-ignored.
  - gitleaks runs in pre-commit and CI.
  - Holding notes are encrypted with MultiFernet.
- **Supply chain.**
  - Lockfiles; `pip-audit`, `npm audit`, Trivy and Dependabot.
  - Containers are non-root and read-only with `no-new-privileges`.

The full threat model is in [docs/SECURITY.md](docs/SECURITY.md).

---

## 14. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "Cannot reach the Lodestar API. Request failed (500)" | Usually the database is not migrated to the latest schema. Run `make migrate seed`, then restart `make dev-api` and `make dev-worker`. Check the API log for the exact error |
| "Cannot reach the Lodestar API" with no status code | The API isn't running, or the Vite proxy can't reach it. Start `make dev-api`. The proxy targets `127.0.0.1:8000`; set `LS_API_URL` if your API runs elsewhere |
| `ModuleNotFoundError: lodestar` | Run commands through `make`, or prefix them with `PYTHONPATH=src` from `backend/` (uv's hidden `.pth` issue on macOS) |
| A run stays `queued` | No worker is running. Start `make dev-worker`. A run stuck for more than 15 minutes is expired automatically on the next request |
| The paper equity curve is empty | Positions advance only on **completed** daily bars. Press **Process new bars**, wait for the hourly tick, or use **Demo replay** in demo mode |
| "Demo data" banner in live use | No `LS_COINGECKO_API_KEY` is set and `LS_DATA_MODE=auto`. Set the key or `LS_DATA_MODE=live` |
| A run ended `failed` after the verifier | The writer could not produce a report that passes verification within two repairs. The Pipeline screen shows each finding. Nothing was published, by design |
| Price mismatch warning | Providers disagree by more than the tolerance. It is flagged as evidence and risk. Change the tolerance in Settings if your sources legitimately differ |
| Start from scratch | `docker compose down -v && make up`. Locally: drop and recreate the database, then `make migrate seed`. To clear only the paper account, use **Reset** on the Paper trading screen |

---

## 15. Extending Lodestar

| To add | Do |
|---|---|
| A new analyst | Subclass `Analyst` (tools, `finalize`, `scripted_plan`, `template_claims`), register a new evidence prefix, add one graph node in `infrastructure/orchestration/langgraph_engine.py` |
| A new data source | Write an adapter behind a port in `application/ports.py`, add a demo equivalent, a cache TTL and a failure mode (data gap or hard failure), and wire it in `container.py` |
| A new verifier rule | Add it to `domain/verification.py` (or `domain/trading/plan.py`) with a positive and a negative test |
| A database change | Edit `infrastructure/db/models.py`, run `uv run alembic revision --autogenerate -m "..."`, review the file, and check that `alembic check` is clean |
| A prompt change | Edit `infrastructure/llm/prompts.py`, bump `PROMPT_VERSION`, and compare verification pass rate, repair loops and dropped claims on sample runs |
| A screen | Add a page in `frontend/src/pages/`, a route in `App.tsx`, data hooks in `api/hooks.ts` (never fetch directly), and colours only via the CSS tokens |

Branching, commit and review conventions are in [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 16. Roadmap and further reading

**Next:**

- A report evaluation set gated in CI.
- Backtests of the analysis scorers.
- Playwright end-to-end tests.
- Calibration of paper results against each plan's stated scenarios.
- Portfolio value history.
- Alerts.

The full list and the deployment path (local → single VM → managed) are in [docs/ROADMAP.md](docs/ROADMAP.md).

| Document | Covers |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture details and design decisions |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model, controls, API key handling |
| [docs/UI.md](docs/UI.md) | Screen layouts, chart and accessibility rules |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phases, next steps, deployment |
| [docs/POLYGON_SNAPSHOT.md](docs/POLYGON_SNAPSHOT.md) | A real exported report (demo data) |
| [skills/README.md](skills/README.md) | The Claude skills |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Workflow and coding standards |

---

## 17. Disclaimer

Lodestar is a personal, read-only research tool and not financial advice. Its scores, risk levels, entry zones, scenario statistics and backtests are rule-based summaries of historical and current data, not predictions, guarantees or price targets. Trading features are paper only: Lodestar never places orders. Crypto assets are highly volatile and you can lose some or all of your money. Verify independently before making any decision.
