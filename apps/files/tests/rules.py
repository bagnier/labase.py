"""Who may rename and delete a file: its uploader, and the org's owners.

The target is the owner's own upload, the one shape both doors can seed — a member acting on it
is the case the route used to refuse alone.
"""

import uuid

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.files.infra.storage import storage_path
from tests.authorization import Action, Fields, Org, Route, Rule, RuleBook

RENAME = Action(
    name="rename",
    sql="update org_files set filename = 'renamed.txt' where id = :file_id returning id",
    route=Route("PATCH", "/files/{file_id}", {"filename": "renamed.txt"}),
)
DELETE = Action(
    name="delete",
    sql="delete from org_files where id = :file_id returning id",
    route=Route("DELETE", "/files/{file_id}"),
)


async def _seed_in_db(session: AsyncSession, org: Org) -> dict[str, Fields]:
    file_id = uuid.uuid7()
    await session.execute(
        text(
            "insert into org_files (id, org_id, uploaded_by, filename, storage_path)"
            " values (:file_id, :org_id, :owner, 'notes.txt', :path)"
        ),
        {
            "file_id": file_id,
            "org_id": org.id,
            "owner": org.people["owner"],
            "path": storage_path(uuid.UUID(org.id), file_id, "notes.txt"),
        },
    )
    return {"owners-file": {"file_id": str(file_id)}}


def _seed_through_routes(owner: httpx.Client, org: Org) -> dict[str, Fields]:
    # Uploaded through the route, so the object the rename moves and the delete removes is there.
    uploaded = owner.post(
        f"/{org.handle}/files", files={"file": ("notes.txt", b"notes", "text/plain")}
    ).raise_for_status()
    return {"owners-file": {"file_id": uploaded.json()["id"]}}


FILES = RuleBook(
    rules=[
        Rule("org_files", "member", RENAME, "owners-file", allowed=False),
        Rule("org_files", "member", DELETE, "owners-file", allowed=False),
        Rule("org_files", "owner", RENAME, "owners-file", allowed=True),
        Rule("org_files", "owner", DELETE, "owners-file", allowed=True),
    ],
    seed_in_db=_seed_in_db,
    seed_through_routes=_seed_through_routes,
)
