import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response

from apps.auth.contract.current import AuthenticatedUser, CurrentUser, RlsSession
from apps.organizations.contract.current import CurrentOrg, CurrentOrgModel
from apps.shared.events.bus import events
from apps.shared.http import (
    HTML_AFTER_DELETE,
    delete_response,
    json_and_html,
    or_404,
    render_list,
    wants_full_page,
    wants_json,
)
from apps.shared.integration.fullpage import fullpage_context
from apps.shared.settings.live import SettingsView
from apps.todo.contract.current import TodoSettings
from apps.todo.contract.events import (
    TodoCreated,
    TodoDeleted,
    TodoEdited,
    TodoTicked,
    TodoUnticked,
)
from apps.todo.domain.models import TodoCreate, TodoEdit, TodoMove, TodoPatch, TodoRead, TodoTick
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


@router.get("", responses=json_and_html(list[TodoRead]))
async def todo_list(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    settings: TodoSettings,
) -> Response:
    return await _render(request, session, current_user, repo, org, settings)


@router.post("", responses=json_and_html(list[TodoRead]))
async def add_todo(
    request: Request,
    body: TodoCreate,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    org_id: CurrentOrg,
    settings: TodoSettings,
) -> Response:
    if not settings.creation_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Task creation is disabled")
    if await repo.count() >= settings.max_items_per_org:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Task limit reached for this organisation")

    title = body.title
    todo = await repo.add(current_user.id, title)
    await events.emit(
        TodoCreated(user_id=current_user.id, org_id=org_id, entity_id=todo.id, entity_name=title),
        session,
    )
    return await _render(request, session, current_user, repo, org, settings)


@router.patch("/{todo_id}", responses=json_and_html(list[TodoRead]))
async def patch_todo(
    request: Request,
    todo_id: uuid.UUID,
    body: TodoPatch,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    org_id: CurrentOrg,
    settings: TodoSettings,
) -> Response:
    todo = or_404(await repo.get(todo_id))
    match body:
        case TodoTick(done=done):
            todo.done = done
            await repo.save(todo)
            ticked = TodoTicked if done else TodoUnticked
            await events.emit(
                ticked(
                    user_id=current_user.id,
                    org_id=org_id,
                    entity_id=todo_id,
                    entity_name=todo.title,
                ),
                session,
            )
        case TodoEdit(title=title):
            todo.title = title
            await repo.save(todo)
            await events.emit(
                TodoEdited(
                    user_id=current_user.id, org_id=org_id, entity_id=todo_id, entity_name=title
                ),
                session,
            )
    return await _render(request, session, current_user, repo, org, settings)


@router.delete("/{todo_id}", status_code=status.HTTP_204_NO_CONTENT, responses=HTML_AFTER_DELETE)
async def delete_todo(
    request: Request,
    todo_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    org_id: CurrentOrg,
    settings: TodoSettings,
) -> Response:
    todo = await repo.get(todo_id)
    if todo:
        await repo.delete(todo)
        await events.emit(
            TodoDeleted(
                user_id=current_user.id,
                org_id=org_id,
                entity_id=todo_id,
                entity_name=todo.title,
            ),
            session,
        )
    if wants_json(request):
        return delete_response(request)
    return await _render(request, session, current_user, repo, org, settings)


@router.put("/{todo_id}/position", responses=json_and_html(list[TodoRead]))
async def move_todo(
    request: Request,
    todo_id: uuid.UUID,
    body: TodoMove,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    settings: TodoSettings,
) -> Response:
    await repo.move_above(todo_id, body.above_id)
    return await _render(request, session, current_user, repo, org, settings)
