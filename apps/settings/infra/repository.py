import uuid

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.settings.domain.models import BOOL_FALSE, ENABLED_KEY, AppSetting, OrgAppSetting


def disabled_apps_select() -> Select[tuple[str]]:
    """Select the slugs of apps whose persisted ``enabled`` value is ``false``.

    Used by the admin-session repository to render the console's toggle state.
    """
    return select(AppSetting.app).where(
        AppSetting.key == ENABLED_KEY, AppSetting.value == BOOL_FALSE
    )


def app_settings_select(app: str) -> Select[tuple[str, str]]:
    """Select every persisted ``(key, value)`` for ``app``.

    Used by the mount-time store so each app can read its whole settings on a throwaway engine.
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
        """Apps whose persisted ``enabled`` value is ``false`` (the admin's standing intent)."""
        return frozenset(await self.session.scalars(disabled_apps_select()))

    async def values(self, app: str) -> dict[str, str]:
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

    # ── per-org overrides (console-managed; apps read them via the RLS session) ──

    async def org_overrides(self, app: str) -> list[dict]:
        """Every override of `app` with its org handle, for the console screen."""
        rows = await self.session.execute(
            text(
                "SELECT s.key, s.value, s.org_id, o.handle FROM org_app_settings s "
                "JOIN organizations o ON o.id = s.org_id "
                "WHERE s.app = :app ORDER BY o.handle, s.key"
            ),
            {"app": app},
        )
        return [dict(row) for row in rows.mappings()]

    async def org_id_by_handle(self, handle: str) -> uuid.UUID | None:
        return await self.session.scalar(
            text("SELECT id FROM organizations WHERE handle = :handle"), {"handle": handle}
        )

    async def set_org_override(self, app: str, key: str, org_id: uuid.UUID, value: str) -> None:
        row = await self.session.get(OrgAppSetting, (app, key, org_id))
        if row is None:
            self.session.add(OrgAppSetting(app=app, key=key, org_id=org_id, value=value))
        else:
            row.value = value

    async def delete_org_override(self, app: str, key: str, org_id: uuid.UUID) -> None:
        row = await self.session.get(OrgAppSetting, (app, key, org_id))
        if row is not None:
            await self.session.delete(row)
