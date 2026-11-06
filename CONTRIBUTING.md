# Contributing and coding standards

## Workflow
1. Branch from `main`: `feat/<topic>`, `fix/<topic>`, `chore/<topic>`.
2. Commit with [Conventional Commits](https://www.conventionalcommits.org): `feat(analysis): add funding-rate signal`.
3. Run `make check` before pushing. CI runs the same checks.
4. Open a PR; keep it focused (one concern per PR) and fill in the template.

## Backend (Python 3.12)
- **Layering is enforced by review:** `domain` imports nothing from the project; `application` imports only `domain` and its ports (no LangGraph, Celery, SQLAlchemy or Anthropic imports); only `infrastructure/container.py` instantiates adapters; `interfaces/` holds the HTTP app, Celery tasks and CLI.
- **Numbers come from code.** Anything a report may mention must be registered as evidence by code first. Never let a model output a figure that is not an evidence value.
- `ruff` (lint + format, 120 cols) and `mypy --strict` must pass. No `Any` leaking out of adapters.
- Async everywhere on I/O paths; never call blocking libraries inside request handlers.
- Raise domain errors (`domain/errors.py`); the API maps them to problem+json. Never return raw exception text for 5xx.
- New analyst = an `Analyst` subclass (tools, `finalize`, `scripted_plan`, `template_claims`) + one graph node in `infrastructure/orchestration/langgraph_engine.py`.
- New external API = new adapter behind a port + a cache TTL + a failure mode (data gap vs. hard failure).
- Database changes: edit `infrastructure/db/models.py`, then `uv run alembic revision --autogenerate -m "..."`, review the file, and make sure `alembic check` is clean.

## Frontend (TypeScript strict)
- Data fetching only through TanStack Query hooks in `src/api/hooks.ts`.
- Never render untrusted text as HTML (`dangerouslySetInnerHTML` is banned by lint).
- Colors only via CSS tokens in `src/index.css`; chart series use `--series-N` in fixed order.

## Testing strategy
| Level | What | Where |
|---|---|---|
| Unit | Indicators, scoring and risk, the verifier (every rule), reconciliation, portfolio maths, address safety, ReAct loop limits, CSV parsing | `backend/tests/unit` |
| Pipeline graph | LangGraph end to end over demo data: parallel analysts, repair loop, fail closed, approval resume, model outage, price mismatch, stale runs | `backend/tests/integration/test_pipeline.py` |
| API integration | HTTP journeys per screen over in-memory adapters, SSE replay/resume, exports, imports, both auth modes | `backend/tests/integration/test_api.py` |
| Adapters | Claude policy/writer against a fake Messages API; live providers against `httpx.MockTransport` | `test_llm_adapters.py`, `test_live_adapters.py` |
| DB integration | Repositories against real Postgres (CI service container) | `backend/tests/integration/test_postgres_repositories.py` |
| Frontend unit | Formatting, SSE parser, pipeline timeline reducer (Vitest) | `frontend/src/**/*.test.ts` |
| Stack smoke | Docker stack: populated dashboard, POL report, add coin → verified report, exports | `scripts/smoke.sh` (CI) |
| Planned | Report eval set, scorer backtests, Playwright E2E | see `docs/ROADMAP.md` |

Rules: every bug fix gets a regression test; any new verifier rule gets a positive and a negative case; no network in tests (use `tests/fakes.py`, demo providers or `httpx.MockTransport`).

## Prompt changes
Edit `infrastructure/llm/prompts.py`, bump `PROMPT_VERSION`, and compare verification pass rate, repair loops and dropped analyst claims on a sample of runs before merging.
