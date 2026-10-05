import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.organizations.contract.queries import org_by_handle, org_handles
from apps.shared.settings.store import AppSetting, OrgAppSetting, disabled_apps_select


class AppSettingRepository:
    """The only writer of ``app_settings``, on the admin session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def table_oid(self, table: str) -> int | None:
        """``table``'s OID, for Studio's table editor link, or ``None``."""
        return await self.session.scalar(text("SELECT (to_regclass(:t))::oid"), {"t": table})

    async def disabled_apps(self) -> frozenset[str]:
        """Apps switched off."""
        return frozenset(await self.session.scalars(disabled_apps_select()))

    async def values(self, app: str) -> dict[str, str]:
        rows = await self.session.scalars(select(AppSetting).where(AppSetting.app_name == app))
        return {row.key: row.value for row in rows}

    async def set(self, app: str, key: str, value: str) -> None:
        # Through the ORM: a raw upsert would bypass the optimistic lock.
        row = await self.session.get(AppSetting, (app, key))
        if row is None:
            self.session.add(AppSetting(app_name=app, key=key, value=value))
        else:
            row.value = value

    # ── per-org overrides (console-managed; apps read them via the RLS session) ──

    async def org_overrides(self, app: str) -> list[dict]:
        """Every override of `app` with its org handle, resolved through the organizations
        contract rather than a JOIN."""
        rows = await self.session.scalars(
            select(OrgAppSetting).where(OrgAppSetting.app_name == app)
        )
        overrides = list(rows)
        handles = await org_handles(self.session, {o.org_id for o in overrides})
        result = [
            {"key": o.key, "value": o.value, "org_id": o.org_id, "handle": handles[o.org_id]}
            for o in overrides
            if o.org_id in handles
        ]
        result.sort(key=lambda r: (r["handle"], r["key"]))
        return result

    async def org_id_by_handle(self, handle: str) -> uuid.UUID | None:
        org = await org_by_handle(self.session, handle)
        return org.id if org is not None else None

    async def set_org_override(self, app: str, key: str, org_id: uuid.UUID, value: str) -> None:
        row = await self.session.get(OrgAppSetting, (app, key, org_id))
        if row is None:
            self.session.add(OrgAppSetting(app_name=app, key=key, org_id=org_id, value=value))
        else:
            row.value = value

    async def delete_org_override(self, app: str, key: str, org_id: uuid.UUID) -> None:
        row = await self.session.get(OrgAppSetting, (app, key, org_id))
        if row is not None:
            await self.session.delete(row)
