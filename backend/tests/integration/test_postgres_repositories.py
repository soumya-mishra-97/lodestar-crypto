"""Repository tests against a real PostgreSQL (runs in CI; skipped locally unless configured).

Requires LS_TEST_DATABASE_URL pointing at a migrated database, e.g.
    LS_TEST_DATABASE_URL=postgresql+asyncpg://lodestar:lodestar@localhost:5432/lodestar_test
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from lodestar.application.ports import ReportSummary
from lodestar.domain.models import ReportKind, ReportStatus, Role, RunStatus
from lodestar.infrastructure.db.repositories import SqlAlchemyUnitOfWork
from lodestar.infrastructure.security.crypto import FieldCipher

DB_URL = os.environ.get("LS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="LS_TEST_DATABASE_URL not set")


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert DB_URL
    eng = create_async_engine(DB_URL)
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE reports, pipeline_events, pipeline_runs, user_settings, holdings, watchlist_items, "
                "assets, users CASCADE"
            )
        )
    yield eng
    await eng.dispose()


@pytest.fixture
def uow(engine: AsyncEngine) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(
        async_sessionmaker(engine, expire_on_commit=False), FieldCipher(Fernet.generate_key().decode())
    )


async def test_full_repository_round_trip(uow: SqlAlchemyUnitOfWork) -> None:
    async with uow as u:
        user = await u.users.add("me@example.com", "hash", Role.OWNER)
        asset = await u.assets.add("polygon-ecosystem-token", "POL", "POL (ex-MATIC)")
        assert (await u.assets.add("polygon-ecosystem-token", "X", "Y")).id == asset.id  # idempotent upsert
        await u.watchlist.add(user.id, asset.id)
        await u.watchlist.add(user.id, asset.id)
        await u.portfolio.upsert(user.id, asset.id, quantity=1000, avg_cost_usd=0.5, notes="secret", source="manual")
        await u.portfolio.upsert(
            user.id, asset.id, quantity=250, avg_cost_usd=None, notes=None, source="wallet:polygon:0xabc"
        )
        await u.portfolio.upsert(user.id, asset.id, quantity=1200, avg_cost_usd=0.5, notes="secret", source="manual")
        await u.settings.put(user.id, {"polymarket_enabled": False})
        await u.settings.put(user.id, {"polymarket_enabled": True})
        run = await u.runs.create(asset.id, user.id, ReportKind.ON_DEMAND, data_mode="demo", llm_mode="deterministic")
        await u.commit()

    async with uow as u:
        assert [a.symbol for a in await u.watchlist.list_assets(user.id)] == ["POL"]
        holdings = sorted(await u.portfolio.list_holdings(user.id), key=lambda h: h.source)
        assert [(h.source, h.quantity) for h in holdings] == [("manual", 1200.0), ("wallet:polygon:0xabc", 250.0)]
        assert holdings[0].notes == "secret"  # decrypted on read, encrypted at rest
        assert await u.settings.get(user.id) == {"polymarket_enabled": True}
        assert (await u.runs.active_for_asset(asset.id)).id == run.id  # type: ignore[union-attr]

        await u.runs.update(run.id, status=RunStatus.RUNNING, current_step="data")
        for n in (1, 2):
            e = await u.events.append(
                run.id, ts=datetime.now(UTC), step="data", type="step", status="running", payload={"n": n}
            )
            assert e.seq == n
        summary = ReportSummary("Headline", "neutral", "favorable", "high", "moderate")
        report_id = await u.reports.create(run.id, asset.id, ReportKind.ON_DEMAND, summary, {"draft": {}})
        assert await u.reports.create(run.id, asset.id, ReportKind.ON_DEMAND, summary, {}) == report_id
        await u.runs.update(run.id, status=RunStatus.AWAITING_APPROVAL)
        await u.commit()

    async with uow as u:
        assert await u.events.max_seq(run.id) == 2
        assert [e.payload["n"] for e in await u.events.list(run.id, after_seq=1)] == [2]
        stored = await u.runs.get(run.id)
        assert stored is not None
        assert stored.started_at
        assert stored.finished_at
        assert await u.runs.active_for_asset(asset.id) is None
        latest = await u.reports.latest_for_assets([asset.id])
        assert latest[asset.id].content == {"draft": {}}
        await u.reports.decide(report_id, ReportStatus.REJECTED, user_id=user.id, note="no")
        await u.commit()

    async with uow as u:
        assert await u.reports.latest_for_assets([asset.id]) == {}  # rejected reports are hidden
        listed = await u.reports.list(status=ReportStatus.REJECTED)
        assert [r.decision_note for r in listed] == ["no"]
        await u.portfolio.remove(user.id, holdings[0].id)
        await u.commit()
        assert len(await u.portfolio.list_holdings(user.id)) == 1
