"""Feature switches — which toggleable apps are disabled, read once at startup.

A server admin can disable an app from the console; the choice persists in ``app_settings``
under the reserved key ``enabled`` and takes effect on the next restart. The composition root
(:mod:`app.main`) loads the disabled set before mounting and stashes it on the :class:`Host`,
so each toggleable app's ``mount`` can gate its user-facing wiring on ``host.enabled(id)``.
"""

import asyncio

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.console.domain.models import AppSetting
from app.shared.config import get_settings

log = structlog.get_logger("labase.console.features")

# The apps a server admin may switch off. Single source of truth for the loader,
# the console toggle, and the user nav.
TOGGLEABLE_APPS = ("todo", "files", "learning")

_ENABLED_KEY = "enabled"


async def load_disabled_apps() -> frozenset[str]:
    """Apps with a persisted ``enabled = false`` override.

    Uses a throwaway engine disposed before returning — the lru_cached admin engine must not
    be touched here, or its asyncpg pool would bind to this short-lived loop and break the
    serving loop.
    """
    settings = get_settings()
    url = settings.database_url_service or settings.database_url
    connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.connect() as conn:
            rows = await conn.scalars(
                select(AppSetting.app).where(
                    AppSetting.key == _ENABLED_KEY, AppSetting.value == "false"
                )
            )
            return frozenset(rows)
    finally:
        await engine.dispose()


def load_disabled_apps_sync() -> frozenset[str]:
    """Synchronous wrapper for the composition root; all-enabled on any failure.

    Degrades to ``frozenset()`` so importing :mod:`app.main` without a reachable DB (unit
    tests) does not blow up — startup simply mounts every app.
    """
    try:
        return asyncio.run(load_disabled_apps())
    except Exception:
        log.warning("console.load_disabled_apps_failed")
        return frozenset()
