"""How the to-do context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the router,
answers the dashboard ``OverviewQuery``, and seeds welcome data on ``OrgCreated``.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.events import OrgCreated
from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.organizations.contract.queries import seed_with_owner
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import (
    SettingDef,
    SettingsChanged,
    SupabaseLink,
    declare_app_settings,
    feature_switch,
    get_app_settings,
)
from apps.shared.host import Host, NavItem
from apps.todo.contract import settings
from apps.todo.domain.models import TodoItem
from apps.todo.infra.repository import TodoRepository
from apps.todo.infra.router import router

_RECENT = 3

_WELCOME_TODOS = [
    "Invite a teammate to this organisation",
    "Upload your first file",
    "Try the spaced-repetition learning decks",
]


# Mounts an org-scoped router under /{org_handle}; mounted last (see apps.main).


def mount(host: Host) -> None:
    # Console presence is kept even when disabled, so an admin can see and re-enable the app.
    host.events.on(ConsoleOverviewQuery, _console_overview)
    _declare_settings()
    if not get_app_settings("todo").enabled:
        return
    settings.read()
    host.events.on(SettingsChanged, settings.reload)
    host.app.include_router(router, prefix=ORG_PREFIX)
    host.register_nav(NavItem("Todos", "clipboard-text", "todos", "/todos", order=10))
    host.events.on(OverviewQuery, _overview)
    host.events.on(OrgCreated, _seed)


def _declare_settings() -> None:
    settings.group = declare_app_settings(
        "todo",
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
