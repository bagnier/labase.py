from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.console.domain.models import AppSetting


class AppSettingRepository:
    """The only writer of ``app_settings`` — driven by the BYPASSRLS admin session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
