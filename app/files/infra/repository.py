import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.files.domain.models import OrgFile


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
    ) -> OrgFile:
        org_file = OrgFile(
            org_id=org_id,
            user_id=user_id,
            filename=filename,
            storage_path=storage_path,
            content_type=content_type,
            size_bytes=size_bytes,
        )
        self.session.add(org_file)
        await self.session.commit()
        return org_file

    async def get(self, file_id: uuid.UUID, org_id: uuid.UUID) -> OrgFile | None:
        result = await self.session.execute(
            select(OrgFile).where(OrgFile.id == file_id, OrgFile.org_id == org_id)
        )
        return result.scalars().first()

    async def delete(self, org_file: OrgFile) -> None:
        await self.session.delete(org_file)
        await self.session.commit()
