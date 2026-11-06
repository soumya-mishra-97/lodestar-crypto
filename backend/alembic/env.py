"""Alembic environment (async engine)."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from lodestar.config import get_settings
from lodestar.infrastructure.db.models import Base

target_metadata = Base.metadata
# LangGraph's Postgres checkpointer manages its own tables (checkpoint*); keep them out of autogenerate/check.
EXTERNAL_TABLE_PREFIXES = ("checkpoint",)


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    return not (type_ == "table" and name is not None and name.startswith(EXTERNAL_TABLE_PREFIXES))


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True, include_name=include_name
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True, include_name=include_name
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
