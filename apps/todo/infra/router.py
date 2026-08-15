import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response

from apps.auth.contract.current import AuthenticatedUser, CurrentUser, RlsSession
from apps.organizations.contract.current import CurrentOrg, CurrentOrgModel
from apps.shared.events.bus import events
from apps.shared.http import (
    delete_response,
    or_404,
    parse_body,
    parse_field,
    render_list,
    wants_full_page,
    wants_json,
)
from apps.shared.page import fullpage_context
from apps.shared.settings import SettingsView
from apps.todo.contract.current import TodoSettings
from apps.todo.contract.events import (
    TodoCreated,
    TodoDeleted,
    TodoEdited,
    TodoTicked,
    TodoUnticked,
)
from apps.todo.domain.models import TodoRead
from apps.todo.infra.repository import TodoRepository


async def _get_todo_repo(session: RlsSession, org_id: CurrentOrg) -> TodoRepository:
    return TodoRepository(session, org_id)


TodoRepo = Annotated[TodoRepository, Depends(_get_todo_repo)]

router = APIRouter(prefix="/todos", tags=["todo"])


async def _render(
    request: Request,
    session: RlsSession,
    current_user: AuthenticatedUser,
    repo: TodoRepo,
    org,
    settings: SettingsView,
) -> Response:
    context = await fullpage_context(session, current_user) if wants_full_page(request) else None
    return render_list(
        request,
        fragment="todo/_list_fragment.html",
        full="todo/list.html",
        items_key="todos",
        schema=TodoRead,
        items=await repo.all(),
        user=current_user,
        org=org,
        context=context,
        extra={"creation_enabled": settings.creation_enabled},
    )


@router.get("", response_class=HTMLResponse)
async def todo_list(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    settings: TodoSettings,
):
    return await _render(request, session, current_user, repo, org, settings)


@router.post("", response_class=HTMLResponse)
async def add_todo(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    org_id: CurrentOrg,
    settings: TodoSettings,
):
    if not settings.creation_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Task creation is disabled")
    if await repo.count() >= settings.max_items_per_org:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Task limit reached for this organisation")

    title = await parse_field(request, "title")
    todo = await repo.add(current_user.id, title)
    await events.emit(
        TodoCreated(user_id=current_user.id, org_id=org_id, entity_id=todo.id, entity_name=title)
    )
    return await _render(request, session, current_user, repo, org, settings)


@router.patch("/{todo_id}", response_class=HTMLResponse)
async def patch_todo(
    request: Request,
    todo_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    org_id: CurrentOrg,
    settings: TodoSettings,
):
    body = await parse_body(request)
    done_raw = body.get("done")
    done = str(done_raw).lower() in ("true", "1", "on") if done_raw is not None else None
    title_raw = body.get("title")
    title = str(title_raw) if title_raw is not None else None
    todo = or_404(await repo.get(todo_id))
    if done is not None:
        todo.done = done
    if title is not None:
        todo.title = title
    await repo.save(todo)
    if done is not None:
        ticked = TodoTicked if done else TodoUnticked
        await events.emit(
            ticked(
                user_id=current_user.id, org_id=org_id, entity_id=todo_id, entity_name=todo.title
            )
        )
    if title is not None:
        await events.emit(
            TodoEdited(user_id=current_user.id, org_id=org_id, entity_id=todo_id, entity_name=title)
        )
    return await _render(request, session, current_user, repo, org, settings)


@router.delete("/{todo_id}", response_class=HTMLResponse)
async def delete_todo(
    request: Request,
    todo_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    org_id: CurrentOrg,
    settings: TodoSettings,
):
    todo = await repo.get(todo_id)
    if todo:
        await repo.delete(todo)
        await events.emit(
            TodoDeleted(
                user_id=current_user.id,
                org_id=org_id,
                entity_id=todo_id,
                entity_name=todo.title,
            )
        )
    if wants_json(request):
        return delete_response(request)
    return await _render(request, session, current_user, repo, org, settings)


@router.put("/{todo_id}/position", response_class=HTMLResponse)
async def move_todo(
    request: Request,
    todo_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    settings: TodoSettings,
):
    body = await request.json()
    above_id = uuid.UUID(body["above_id"]) if body.get("above_id") else None
    await repo.move_above(todo_id, above_id)
    return await _render(request, session, current_user, repo, org, settings)
