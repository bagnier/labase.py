"""Startup reader for per-app settings — answers "what are my overrides?" at mount time.

A server admin can configure a toggleable app from the console, including disabling it; the
choices persist in ``app_settings`` and take effect on the next restart. This module owns the
DB read (on a throwaway engine); :func:`app.console.contract.settings.get_app_settings` wraps it
into an :class:`~app.console.contract.settings.AppSettings`, so no context needs a pre-loaded
set.
"""

import asyncio

import structlog
from sqlalchemy.ext.asyncio import create_async_engine

from app.console.infra.repository import app_settings_select
from app.shared.config import get_technical_settings

log = structlog.get_logger("labase.console.startup")


async def _load(app_id: str) -> dict[str, str]:
    """Read every override for ``app_id`` on a throwaway engine.

    The engine is disposed before returning — the lru_cached admin engine must not be
    touched here, or its asyncpg pool would bind to this short-lived loop and break the
    serving loop.
    """
    settings = get_technical_settings()
    url = settings.database_url_service or settings.database_url
    connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(app_settings_select(app_id))).all()
    finally:
        await engine.dispose()
    return {key: value for key, value in rows}


def load_app_overrides(app_id: str) -> dict[str, str]:
    """An app's persisted ``key → value`` overrides, read straight from ``app_settings``.

    Degrades to ``{}`` on any failure, so importing/mounting without a reachable DB (unit
    tests) never blows up. Wrapped by :func:`app.console.contract.settings.get_app_settings`.
    """
    try:
        return asyncio.run(_load(app_id))
    except Exception:
        log.warning("console.app_settings_failed", app_id=app_id)
        return {}
