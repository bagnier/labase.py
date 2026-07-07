import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.files.domain.models import OrgFile, OrgFileShareToken
from apps.shared import clock
from apps.shared.persistence.repository import BaseRepository, OrgScopedRepository
from apps.shared.settings import get_settings


class OrgFileRepository(OrgScopedRepository[OrgFile]):
    model = OrgFile
    default_order = OrgFile.created_at.desc()

    async def total_size(self) -> int:
        """Total bytes stored by this organisation, across all its files."""
        return int(
            await self.session.scalar(
                select(func.coalesce(func.sum(OrgFile.size_bytes), 0)).where(
                    OrgFile.org_id == self.org_id
                )
            )
            or 0
        )

    async def add(
        self,
        user_id: uuid.UUID,
        filename: str,
        storage_path: str,
        content_type: str,
        size_bytes: int,
        uploader_email: str = "",
    ) -> OrgFile:
        org_file = OrgFile(
            org_id=self.org_id,
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

    async def rename(self, org_file: OrgFile, new_filename: str, new_storage_path: str) -> None:
        org_file.filename = new_filename
        org_file.storage_path = new_storage_path

    async def add_share_token(self, file_id: uuid.UUID) -> OrgFileShareToken:
        effective = await get_settings("files").for_org(self.session, self.org_id)
        token = OrgFileShareToken(
            file_id=file_id,
            expires_at=clock.now() + timedelta(days=effective.share_link_ttl_days),
        )
        self.session.add(token)
        await self.session.flush()
        return token


class FileShareRepository(BaseRepository[OrgFile]):
    """Admin-scoped repository for public share download — no org isolation."""

    model = OrgFile

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_share_token(self, token: uuid.UUID) -> OrgFileShareToken | None:
        return await self.session.scalar(
            select(OrgFileShareToken).where(OrgFileShareToken.token == token)
        )

    async def count_and_size(self) -> tuple[int, int]:
        """Server-wide file count and total size, across every organisation."""
        row = (
            await self.session.execute(
                select(func.count(OrgFile.id), func.coalesce(func.sum(OrgFile.size_bytes), 0))
            )
        ).one()
        return int(row[0]), int(row[1])
