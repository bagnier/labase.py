"""Welcome file the files context drops into a freshly created organisation.

Public surface consumed by the composition root (:mod:`app.seeding`) via the
``org.created`` hook. Runs post-commit as a background task.
"""

import uuid

from sqlalchemy import select

from app.files.infra.repository import OrgFileRepository
from app.files.infra.storage import BUCKET, storage_path, user_storage_client
from app.organizations.domain.models import Membership, OrgRole
from app.shared.persistence.database import admin_session_factory

_WELCOME_FILENAME = "welcome.txt"
_WELCOME_BODY = (
    b"Welcome to your organisation!\n\n"
    b"This is your shared file space. Upload documents here and share them with\n"
    b"your teammates via expiring links.\n"
)


async def seed(org_id: uuid.UUID, access_token: str) -> None:
    async with admin_session_factory()() as session:
        owner_id = await session.scalar(
            select(Membership.auth_user_id).where(
                Membership.org_id == org_id, Membership.role == OrgRole.owner
            )
        )

    file_id = uuid.uuid4()
    path = storage_path(org_id, file_id, _WELCOME_FILENAME)
    storage = user_storage_client(access_token)
    await storage.from_(BUCKET).upload(path, _WELCOME_BODY, {"content-type": "text/plain"})

    async with admin_session_factory()() as session:
        repo = OrgFileRepository(session, org_id)
        await repo.add(
            user_id=owner_id,
            filename=_WELCOME_FILENAME,
            storage_path=path,
            content_type="text/plain",
            size_bytes=len(_WELCOME_BODY),
        )
        await session.commit()
