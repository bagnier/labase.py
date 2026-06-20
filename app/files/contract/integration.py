"""How the files context plugs into the running app.

Single composition entry (:func:`register`, called from :mod:`app.main`): mounts the public
share router and the org-scoped router, claims the ``files`` slug, answers the dashboard
``OverviewQuery``, and drops a welcome file on ``OrgCreated``.
"""

import uuid

from fastapi import FastAPI
from sqlalchemy import select

from app.files.infra.repository import OrgFileRepository
from app.files.infra.router import public_router, router
from app.files.infra.storage import BUCKET, storage_path, user_storage_client
from app.organizations.contract import ORG_PREFIX
from app.organizations.contract.events import OrgCreated
from app.organizations.contract.overviews import Overview, OverviewQuery
from app.organizations.domain.models import Membership, OrgRole
from app.shared.host import Host
from app.shared.persistence.database import admin_session_factory

_RECENT = 3

_WELCOME_FILENAME = "welcome.txt"
_WELCOME_BODY = (
    b"Welcome to your organisation!\n\n"
    b"This is your shared file space. Upload documents here and share them with\n"
    b"your teammates via expiring links.\n"
)


def register(app: FastAPI, host: Host) -> None:
    app.include_router(public_router)
    app.include_router(router, prefix=ORG_PREFIX)
    host.events.on(OverviewQuery, _overview)
    host.events.on(OrgCreated, _seed)
    host.reserve("files")


def _human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:g} {unit}"
        size /= 1024
    return f"{size:g} GB"


async def _overview(query: OverviewQuery) -> Overview:
    files = await OrgFileRepository(query.session, query.org_id).all()
    if files:
        total = sum(f.size_bytes for f in files)
        lines = [f"{len(files)} files", _human_size(total)]
    else:
        lines = ["No files yet"]
    return Overview(
        key="files",
        title="Files",
        icon="folder",
        href="files",
        template="files/_overview.html",
        data={"lines": lines, "recent": [f.filename for f in files[:_RECENT]]},
    )


async def _seed(event: OrgCreated) -> None:
    async with admin_session_factory()() as session:
        owner_id = await session.scalar(
            select(Membership.auth_user_id).where(
                Membership.org_id == event.org_id, Membership.role == OrgRole.owner
            )
        )

    file_id = uuid.uuid4()
    path = storage_path(event.org_id, file_id, _WELCOME_FILENAME)
    storage = user_storage_client(event.access_token)
    await storage.from_(BUCKET).upload(path, _WELCOME_BODY, {"content-type": "text/plain"})

    async with admin_session_factory()() as session:
        repo = OrgFileRepository(session, event.org_id)
        await repo.add(
            user_id=owner_id,
            filename=_WELCOME_FILENAME,
            storage_path=path,
            content_type="text/plain",
            size_bytes=len(_WELCOME_BODY),
        )
        await session.commit()
