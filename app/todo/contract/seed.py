"""Welcome data the todo context drops into a freshly created organisation.

Public surface consumed by the composition root (:mod:`app.seeding`) via the
``org.created`` hook. Runs post-commit as a background task.
"""

import uuid

from sqlalchemy import select

from app.organizations.domain.models import Membership, OrgRole
from app.shared.persistence.database import admin_session_factory
from app.todo.infra.repository import TodoRepository

_WELCOME_TODOS = [
    "Invite a teammate to this organisation",
    "Upload your first file",
    "Try the spaced-repetition learning decks",
]


async def seed(org_id: uuid.UUID, access_token: str) -> None:
    async with admin_session_factory()() as session:
        owner_id = await session.scalar(
            select(Membership.auth_user_id).where(
                Membership.org_id == org_id, Membership.role == OrgRole.owner
            )
        )
        repo = TodoRepository(session, org_id)
        # add() prepends, so insert in reverse to keep list order.
        for title in reversed(_WELCOME_TODOS):
            await repo.add(owner_id, title)
        await session.commit()
