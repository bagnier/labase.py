"""How the to-do context plugs into the running app.

Single composition entry (:func:`register`, called from :mod:`app.main`): mounts the router,
answers the dashboard ``OverviewQuery``, and seeds welcome data on ``OrgCreated``.
"""

from fastapi import FastAPI
from sqlalchemy import select

from app.organizations.contract import ORG_PREFIX
from app.organizations.contract.events import OrgCreated
from app.organizations.contract.overviews import Overview, OverviewQuery
from app.organizations.domain.models import Membership, OrgRole
from app.shared.host import Host
from app.shared.persistence.database import admin_session_factory
from app.todo.infra.repository import TodoRepository
from app.todo.infra.router import router

_RECENT = 3

_WELCOME_TODOS = [
    "Invite a teammate to this organisation",
    "Upload your first file",
    "Try the spaced-repetition learning decks",
]


def register(app: FastAPI, host: Host) -> None:
    app.include_router(router, prefix=ORG_PREFIX)
    host.events.on(OverviewQuery, _overview)
    host.events.on(OrgCreated, _seed)


async def _overview(query: OverviewQuery) -> Overview:
    items = await TodoRepository(query.session, query.org_id).all()
    open_items = [t for t in items if not t.done]
    done = len(items) - len(open_items)
    lines = [f"{len(open_items)} open", f"{done} done"] if items else ["No tasks yet"]
    return Overview(
        key="todo",
        title="To-do",
        icon="clipboard-text",
        href="todos",
        template="todo/_overview.html",
        data={"lines": lines, "recent": [t.title for t in open_items[:_RECENT]]},
    )


async def _seed(event: OrgCreated) -> None:
    async with admin_session_factory()() as session:
        owner_id = await session.scalar(
            select(Membership.auth_user_id).where(
                Membership.org_id == event.org_id, Membership.role == OrgRole.owner
            )
        )
        repo = TodoRepository(session, event.org_id)
        # add() prepends, so insert in reverse to keep list order.
        for title in reversed(_WELCOME_TODOS):
            await repo.add(owner_id, title)
        await session.commit()
