from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.console.domain.models import BOOL_FALSE, ENABLED_KEY, AppSetting


def disabled_apps_select() -> Select[tuple[str]]:
    """Select the slugs of apps with a persisted ``enabled = false`` override.

    Used by the admin-session repository to render the console's toggle state.
    """
    return select(AppSetting.app).where(
        AppSetting.key == ENABLED_KEY, AppSetting.value == BOOL_FALSE
    )


def app_settings_select(app: str) -> Select[tuple[str, str]]:
    """Select every persisted ``(key, value)`` override for ``app``.

    Used by the startup loader so each app can read its whole settings on a throwaway engine
    and decide whether it is enabled.
    """
    return select(AppSetting.key, AppSetting.value).where(AppSetting.app == app)


class AppSettingRepository:
    """The only writer of ``app_settings`` — driven by the BYPASSRLS admin session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def table_oid(self, table: str) -> int | None:
        """Postgres OID of ``table`` (resolved via the search_path), or ``None`` if absent.

        Studio's table editor deep link is OID-keyed, so the console resolves the name here.
        """
        return await self.session.scalar(text("SELECT (to_regclass(:t))::oid"), {"t": table})

    async def disabled_apps(self) -> frozenset[str]:
        """Apps with a persisted ``enabled = false`` override (the admin's standing intent)."""
        return frozenset(await self.session.scalars(disabled_apps_select()))

    async def overrides(self, app: str) -> dict[str, str]:
        rows = await self.session.scalars(select(AppSetting).where(AppSetting.app == app))
        return {row.key: row.value for row in rows}

    async def set(self, app: str, key: str, value: str) -> None:
        # ORM read-modify-write so version_id_col (optimistic lock) and the updated_at
        # trigger engage; a raw upsert would bypass both.
        row = await self.session.get(AppSetting, (app, key))
        if row is None:
            self.session.add(AppSetting(app=app, key=key, value=value))
        else:
            row.value = value
