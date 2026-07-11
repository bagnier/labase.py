"""How the to-do context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the router,
answers the dashboard ``OverviewQuery``, and seeds welcome data on ``OrgCreated``.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.events import OrgCreated
from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.organizations.contract.queries import seed_with_owner
from apps.shared.host import AppManifest, Host, MountPhase, NavItem
from apps.shared.settings import SettingDef, SettingsDeclaration, SupabaseLink, feature_switch
from apps.todo.domain.models import TodoItem
from apps.todo.infra.repository import TodoRepository
from apps.todo.infra.router import router

PHASE = MountPhase.ORG

_RECENT = 3

_WELCOME_TODOS = [
    "Invite a teammate to this organisation",
    "Upload your first file",
    "Try the spaced-repetition learning decks",
]


def mount(host: Host) -> None:
    host.register_app(
        AppManifest(
            settings=_declare_settings(),
            on=[(ConsoleOverviewQuery, _console_overview)],
            routers=[(router, ORG_PREFIX)],
            nav=[NavItem("Todos", "clipboard-text", "todos", "/todos", order=10)],
            when_enabled=[(OverviewQuery, _overview), (OrgCreated, _seed)],
        )
    )


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name="todo",
        defs=[
            feature_switch(),
            SettingDef("creation_enabled", "boolean", "true", "Allow members to create tasks"),
            SettingDef("max_items_per_org", "number", "500", "Maximum tasks per organisation"),
        ],
        supabase=SupabaseLink("Browse tasks in Supabase", table="todos"),
    )


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    total = await query.session.scalar(select(func.count()).select_from(TodoItem)) or 0
    done = (
        await query.session.scalar(select(func.count()).select_from(TodoItem).where(TodoItem.done))
        or 0
    )
    lines = [f"{total - done} open", f"{done} done"] if total else ["No tasks yet"]
    return ConsoleOverview(key="todo", title="To-do", icon="clipboard-text", data={"lines": lines})


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
    async def seed(session: AsyncSession, owner_id: uuid.UUID) -> None:
        repo = TodoRepository(session, event.org_id)
        # add() prepends, so insert in reverse to keep list order.
        for title in reversed(_WELCOME_TODOS):
            await repo.add(owner_id, title)

    await seed_with_owner(event.org_id, seed)
