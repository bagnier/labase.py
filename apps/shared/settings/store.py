"""The live settings tables, and the reads and seeds ``mount()`` makes before the event loop runs.

Those go through a throwaway engine under :func:`asyncio.run`: the cached admin engine's asyncpg
pool would bind to that short-lived loop and break the serving one.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy import ForeignKey, Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.logs.dependency import log_dependency_failure
from apps.shared.persistence.base import Base, Timestamped, Versioned
from apps.shared.persistence.database import admin_url, search_path_connect_args
from apps.shared.settings.env import get_technical_settings

log = structlog.get_logger(__name__)

BOOL_TRUE = "true"
BOOL_FALSE = "false"

# The on/off switch's key.
ENABLED_KEY = "enabled"


class AppSetting(Base, Versioned, Timestamped):
    """A server-wide setting value, seeded at declaration, edited from the console."""

    __tablename__ = "app_settings"

    app_name: Mapped[str] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str]  # coerced by the declared SettingDef.type


class OrgAppSetting(Base, Versioned, Timestamped):
    """A per-org override of an `AppSetting`, edited from the console."""

    __tablename__ = "org_app_settings"

    app_name: Mapped[str] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    value: Mapped[str]


def disabled_apps_select() -> Select[tuple[str]]:
    """The apps switched off."""
    return select(AppSetting.app_name).where(
        AppSetting.key == ENABLED_KEY, AppSetting.value == BOOL_FALSE
    )


def _app_settings_select(app: str) -> Select[tuple[str, str]]:
    return select(AppSetting.key, AppSetting.value).where(AppSetting.app_name == app)


async def _on_throwaway_engine[T](work: Callable[[AsyncConnection], Awaitable[T]]) -> T:
    settings = get_technical_settings()
    engine = create_async_engine(
        admin_url(settings), connect_args=search_path_connect_args(settings)
    )
    try:
        async with engine.begin() as conn:
            return await work(conn)
    finally:
        await engine.dispose()


def read_values(app: str) -> dict[str, str]:
    """An app's stored values, or ``{}`` when the database is unreachable."""

    async def _work(conn: AsyncConnection) -> dict[str, str]:
        rows = (await conn.execute(_app_settings_select(app))).all()
        return {key: value for key, value in rows}

    try:
        return asyncio.run(_on_throwaway_engine(_work))
    except Exception as exc:
        # The app now runs on defaults, silently wrong wherever a stored value differs: an issue.
        log_dependency_failure(log, "settings.read_values_failed", exc, app=app)
        return {}


def seed_values(app: str, initial: dict[str, str]) -> None:
    """Insert the settings not stored yet, leaving existing values alone. Logs and returns when
    the database is unreachable."""
    if not initial:
        return

    async def _work(conn: AsyncConnection) -> None:
        rows = [{"app_name": app, "key": key, "value": value} for key, value in initial.items()]
        stmt = (
            insert(AppSetting)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["app_name", "key"])
        )
        await conn.execute(stmt)

    try:
        asyncio.run(_on_throwaway_engine(_work))
    except Exception as exc:
        log_dependency_failure(log, "settings.seed_values_failed", exc, app=app)
