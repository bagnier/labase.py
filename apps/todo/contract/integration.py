"""How the to-do context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the router,
answers the dashboard ``OverviewQuery``, and seeds welcome data on ``OrganizationCreated``.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.events import OrganizationCreated
from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.organizations.contract.queries import seed_org_welcome
from apps.shared.host import AppManifest, Host, MountPhase, NavItem
from apps.shared.outbox import on_async
from apps.shared.settings import SettingDef, SettingsDeclaration, SupabaseLink, feature_switch
from apps.todo.contract.events import TodoTicked
from apps.todo.domain.models import TodoItem
from apps.todo.infra.completion_stats import bump_completion, completion_count
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
    settings = host.register_app(
        AppManifest(
            settings=_declare_settings(),
            provides=[(ConsoleOverviewQuery, _console_overview)],
            routers=[(router, ORG_PREFIX)],
            nav=[NavItem("Todos", "clipboard-text", "todos", "/todos", order=10)],
            consumes_when_enabled=[(OrganizationCreated, "todo_welcome", _seed)],
            provides_when_enabled=[(OverviewQuery, _overview)],
        )
    )
    if not settings.enabled:
        return
    # Durable async consumer: every `emit(TodoTicked)` fans out here through the outbox and bumps
    # the org's cumulative completion counter — the producer's emit site never changed. Runs on the
    # admin session (server-owned aggregate) and is idempotent (at-least-once delivery may repeat).
    on_async(TodoTicked, "completion_counter", _bump_completed, as_actor=False, idempotent=True)


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
    # Cumulative completions, kept by the durable async consumer of todo.ticked — a distinct
    # "N completed" badge (not the live "N done"), so the dashboard reflects the event pipeline.
    lines.append(f"{await completion_count(query.session, query.org_id)} completed")
    return Overview(
        key="todo",
        title="To-do",
        icon="clipboard-text",
        href="todos",
        template="todo/_overview.html",
        data={"lines": lines, "recent": [t.title for t in open_items[:_RECENT]]},
    )


async def _bump_completed(session: AsyncSession, event: TodoTicked) -> None:
    """Durable consumer of ``todo.ticked``: keep the org's cumulative completion counter."""
    if event.org_id is not None:
        await bump_completion(session, uuid.UUID(event.org_id))


async def _seed(session: AsyncSession, event: OrganizationCreated) -> None:
    await seed_org_welcome(session, event.org_id, _seed_welcome)


async def _seed_welcome(session: AsyncSession, org_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    repo = TodoRepository(session, org_id)
    # add() prepends, so insert in reverse to keep list order.
    for title in reversed(_WELCOME_TODOS):
        await repo.add(owner_id, title)
