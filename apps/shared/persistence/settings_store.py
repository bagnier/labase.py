"""Mount-time CRUD for per-app settings — the console's settings repository at startup.

Apps **declare** their settings and **read** their values inside ``mount()`` (sync, before the
serving loop), via :mod:`apps.shared.settings`. This module owns the persisted tables and the
concrete DB plumbing for that moment: a throwaway engine driven by :func:`asyncio.run`.

The lru_cached admin engine must not be touched here, or its asyncpg pool would bind to this
short-lived loop and break the serving loop — hence the disposable engine.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy import ForeignKey, Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.config import get_technical_settings
from apps.shared.persistence.base import Base, Timestamped, Versioned

log = structlog.get_logger("labase.settings.store")

# Stored form of a boolean setting value.
BOOL_TRUE = "true"
BOOL_FALSE = "false"

# Reserved key for an app's on/off switch, stored like any other setting value.
ENABLED_KEY = "enabled"


class AppSetting(Base, Versioned, Timestamped):
    """The persisted value of one app setting — seeded on declaration, edited from the console."""

    __tablename__ = "app_settings"

    app: Mapped[str] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str]  # stored as text; coerced by the app's declared SettingDef.type


class OrgAppSetting(Base, Versioned, Timestamped):
    """A per-organisation override of one app setting — managed from the console.

    Unset (app, key, org) triples fall back to the server-wide `AppSetting` value.
    """

    __tablename__ = "org_app_settings"

    app_name: Mapped[str] = mapped_column("app", primary_key=True)  # DB column is still "app"
    key: Mapped[str] = mapped_column(primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    value: Mapped[str]


def disabled_apps_select() -> Select[tuple[str]]:
    """Select the slugs of apps whose persisted ``enabled`` value is ``false``.

    Used by the admin-session repository to render the console's toggle state.
    """
    return select(AppSetting.app).where(
        AppSetting.key == ENABLED_KEY, AppSetting.value == BOOL_FALSE
    )


def _app_settings_select(app: str) -> Select[tuple[str, str]]:
    """Every persisted ``(key, value)`` for ``app`` — read at mount on a throwaway engine."""
    return select(AppSetting.key, AppSetting.value).where(AppSetting.app == app)


async def _on_throwaway_engine[T](work: Callable[[AsyncConnection], Awaitable[T]]) -> T:
    """Run ``work`` on a fresh connection from a disposable engine, then dispose it."""
    settings = get_technical_settings()
    url = settings.supabase_database_admin_url or settings.supabase_database_user_url
    connect_args = {
        "server_settings": {"search_path": f"{settings.supabase_database_schema},public"}
    }
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
        rows = (await conn.execute(_app_settings_select(app))).all()
        return {key: value for key, value in rows}

    try:
        return asyncio.run(_on_throwaway_engine(_work))
    except Exception:
        log.exception("console.read_values_failed", app=app)
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
        log.exception("console.seed_values_failed", app=app)
