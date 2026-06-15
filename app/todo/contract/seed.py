"""Welcome data the todo context drops into a freshly created organisation.

Public surface consumed by the composition root (:mod:`app.seeding`) via the
``org.created`` hook. Runs inside the org-creating transaction.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.todo.infra.repository import TodoRepository

_WELCOME_TODOS = [
    "Invite a teammate to this organisation",
    "Upload your first file",
    "Try the spaced-repetition learning decks",
]


async def seed(session: AsyncSession, org_id: uuid.UUID, owner_user_id: uuid.UUID) -> None:
    repo = TodoRepository(session, org_id)
    # add() prepends, so insert in reverse to keep list order.
    for title in reversed(_WELCOME_TODOS):
        await repo.add(owner_user_id, title)
