"""Welcome file the files context drops into a freshly created organisation.

Public surface consumed by the composition root (:mod:`app.seeding`) via the
``org.created`` hook. Runs inside the org-creating transaction.

The Storage upload itself is not transactional: if the surrounding transaction
rolls back afterwards, the uploaded blob is orphaned (minor, acceptable). We
therefore upload first, then insert the DB row.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.files.infra.repository import OrgFileRepository
from app.files.infra.storage import BUCKET, admin_storage, storage_path

_WELCOME_FILENAME = "welcome.txt"
_WELCOME_BODY = (
    b"Welcome to your organisation!\n\n"
    b"This is your shared file space. Upload documents here and share them with\n"
    b"your teammates via expiring links.\n"
)


async def seed(session: AsyncSession, org_id: uuid.UUID, owner_user_id: uuid.UUID) -> None:
    file_id = uuid.uuid4()
    path = storage_path(org_id, file_id, _WELCOME_FILENAME)
    storage = admin_storage()
    await storage.from_(BUCKET).upload(path, _WELCOME_BODY, {"content-type": "text/plain"})

    repo = OrgFileRepository(session, org_id)
    await repo.add(
        user_id=owner_user_id,
        filename=_WELCOME_FILENAME,
        storage_path=path,
        content_type="text/plain",
        size_bytes=len(_WELCOME_BODY),
    )
