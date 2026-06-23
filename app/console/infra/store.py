"""Mount-time CRUD for per-app settings — the console's settings repository at startup.

Apps **declare** their settings and **read** their values inside ``mount()`` (sync, before the
serving loop), via :mod:`app.console.contract.settings`. This module owns the concrete DB
plumbing for that moment: a throwaway engine driven by :func:`asyncio.run`.

The lru_cached admin engine must not be touched here, or its asyncpg pool would bind to this
short-lived loop and break the serving loop — hence the disposable engine.
"""

import asyncio
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.console.domain.models import AppSetting
from app.console.infra.repository import app_settings_select
from app.shared.config import get_technical_settings

log = structlog.get_logger("labase.console.store")


async def _on_throwaway_engine[T](work: Callable[[AsyncConnection], Awaitable[T]]) -> T:
    """Run ``work`` on a fresh connection from a disposable engine, then dispose it."""
    settings = get_technical_settings()
    url = settings.database_url_service or settings.database_url
    connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.begin() as conn:
            return await work(conn)
    finally:
        await engine.dispose()


def read_values(app: str) -> dict[str, str]:
    """An app's persisted ``key → value`` settings, read straight from ``app_settings``.

    Degrades to ``{}`` on any failure, so mounting without a reachable DB (unit tests) never
    blows up.
    """

    async def _work(conn: AsyncConnection) -> dict[str, str]:
        rows = (await conn.execute(app_settings_select(app))).all()
        return {key: value for key, value in rows}

    try:
        return asyncio.run(_on_throwaway_engine(_work))
    except Exception:
        log.warning("console.read_values_failed", app=app)
        return {}


def seed_values(app: str, initial: dict[str, str]) -> None:
    """Create the row for each declared setting that does not exist yet (create-if-absent).

    The declared value is the setting's initial value; an existing value is left untouched.
    No-op on any failure, so mounting without a reachable DB never blows up.
    """
    if not initial:
        return

    async def _work(conn: AsyncConnection) -> None:
        rows = [{"app": app, "key": key, "value": value} for key, value in initial.items()]
        stmt = insert(AppSetting).values(rows).on_conflict_do_nothing(index_elements=["app", "key"])
        await conn.execute(stmt)

    try:
        asyncio.run(_on_throwaway_engine(_work))
    except Exception:
        log.warning("console.seed_values_failed", app=app)
