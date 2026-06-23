"""How the to-do context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`app.main`): mounts the router,
answers the dashboard ``OverviewQuery``, and seeds welcome data on ``OrgCreated``.
"""

from fastapi import FastAPI
from sqlalchemy import func, select

from app.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from app.console.contract.settings import (
    ConsoleSettingsQuery,
    SettingDef,
    SettingsGroup,
    SupabaseLink,
    feature_switch,
    get_app_settings,
)
from app.organizations.contract import ORG_PREFIX
from app.organizations.contract.events import OrgCreated
from app.organizations.contract.overviews import Overview, OverviewQuery
from app.organizations.contract.queries import get_org_owner_id
from app.shared.host import Host, NavItem
from app.shared.persistence.database import admin_session_factory
from app.todo.domain.models import TodoItem
from app.todo.infra.repository import TodoRepository
from app.todo.infra.router import router

_RECENT = 3

_WELCOME_TODOS = [
    "Invite a teammate to this organisation",
    "Upload your first file",
    "Try the spaced-repetition learning decks",
]


# Mounts an org-scoped router under /{org_handle}; mounted last (see app.main).


def mount(app: FastAPI, host: Host) -> None:
    # Console presence is kept even when disabled, so an admin can see and re-enable the app.
    host.events.on(ConsoleOverviewQuery, _console_overview)
    host.events.on(ConsoleSettingsQuery, _console_settings)
    settings = get_app_settings("todo")
    if not settings.enabled:
        return
    app.include_router(router, prefix=ORG_PREFIX)
    host.register_nav(NavItem("Todos", "clipboard-text", "todos", "/todos", order=10))
    host.events.on(OverviewQuery, _overview)
    host.events.on(OrgCreated, _seed)


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    total = await query.session.scalar(select(func.count()).select_from(TodoItem)) or 0
    done = (
        await query.session.scalar(select(func.count()).select_from(TodoItem).where(TodoItem.done))
        or 0
    )
    lines = [f"{total - done} open", f"{done} done"] if total else ["No tasks yet"]
    return ConsoleOverview(key="todo", title="To-do", icon="clipboard-text", data={"lines": lines})


async def _console_settings(query: ConsoleSettingsQuery) -> SettingsGroup:
    return SettingsGroup(
        app="todo",
        defs=[
            feature_switch(),
            SettingDef("creation_enabled", "boolean", "true", "Allow members to create tasks"),
            SettingDef("max_items_per_org", "number", "500", "Maximum tasks per organisation"),
        ],
        supabase=SupabaseLink("Browse tasks in Supabase", table="todos"),
    )


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
        owner_id = await get_org_owner_id(session, event.org_id)
        if owner_id is None:
            return
        repo = TodoRepository(session, event.org_id)
        # add() prepends, so insert in reverse to keep list order.
        for title in reversed(_WELCOME_TODOS):
            await repo.add(owner_id, title)
        await session.commit()
