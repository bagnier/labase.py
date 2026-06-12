import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.files.domain.models import OrgFile, OrgFileShareToken
from app.shared import clock

_SHARE_TOKEN_TTL_DAYS = 7


class OrgFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_org(self, org_id: uuid.UUID) -> list[OrgFile]:
        result = await self.session.execute(
            select(OrgFile).where(OrgFile.org_id == org_id).order_by(OrgFile.created_at.desc())
        )
        return list(result.scalars().all())

    async def add(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        filename: str,
        storage_path: str,
        content_type: str,
        size_bytes: int,
        uploader_email: str = "",
    ) -> OrgFile:
        org_file = OrgFile(
            org_id=org_id,
            user_id=user_id,
            filename=filename,
            storage_path=storage_path,
            content_type=content_type,
            size_bytes=size_bytes,
            uploader_email=uploader_email,
            created_at=clock.now(),
        )
        self.session.add(org_file)
        await self.session.flush()
        return org_file

    async def get(self, file_id: uuid.UUID, org_id: uuid.UUID) -> OrgFile | None:
        result = await self.session.execute(
            select(OrgFile).where(OrgFile.id == file_id, OrgFile.org_id == org_id)
        )
        return result.scalars().first()

    async def get_by_id(self, file_id: uuid.UUID) -> OrgFile | None:
        result = await self.session.execute(select(OrgFile).where(OrgFile.id == file_id))
        return result.scalars().first()

    async def rename(self, org_file: OrgFile, new_filename: str) -> None:
        org_file.filename = new_filename

    async def delete(self, org_file: OrgFile) -> None:
        await self.session.delete(org_file)

    async def add_share_token(self, file_id: uuid.UUID) -> OrgFileShareToken:
        token = OrgFileShareToken(
            file_id=file_id,
            expires_at=clock.now() + timedelta(days=_SHARE_TOKEN_TTL_DAYS),
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_share_token(self, token: uuid.UUID) -> OrgFileShareToken | None:
        result = await self.session.execute(
            select(OrgFileShareToken).where(OrgFileShareToken.token == token)
        )
        return result.scalars().first()
