import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response

from apps.auth.contract.current import AuthenticatedUser, CurrentUser, RlsSession
from apps.organizations.contract.current import CurrentOrg, CurrentOrgModel
from apps.shared.http import or_404, parse_body, parse_field, render_list, wants_full_page
from apps.shared.observability.audit import record_audit_event
from apps.shared.page import shell_context
from apps.todo.contract import settings
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
) -> Response:
    shell = await shell_context(session, current_user) if wants_full_page(request) else None
    return render_list(
        request,
        fragment="todo/_list_fragment.html",
        full="todo/list.html",
        items_key="todos",
        schema=TodoRead,
        items=await repo.all(),
        user=current_user,
        org=org,
        shell=shell,
        extra={"creation_enabled": settings.creation_enabled},
    )


@router.get("", response_class=HTMLResponse)
async def todo_list(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
):
    return await _render(request, session, current_user, repo, org)


@router.post("", response_class=HTMLResponse)
async def add_todo(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    org_id: CurrentOrg,
):
    if not settings.creation_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Task creation is disabled")
    if await repo.count() >= settings.max_items_per_org:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Task limit reached for this organisation")

    title = await parse_field(request, "title")
    todo = await repo.add(uuid.UUID(current_user.id), title)
    record_audit_event(
        bg,
        level="info",
        event="todo.created",
        user_id=current_user.id,
        org_id=str(org_id),
        todo_id=str(todo.id),
    )
    return await _render(request, session, current_user, repo, org)


@router.patch("/{todo_id}", response_class=HTMLResponse)
async def patch_todo(
    request: Request,
    bg: BackgroundTasks,
    todo_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    org_id: CurrentOrg,
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
    if title is not None:
        record_audit_event(
            bg,
            level="info",
            event="todo.updated",
            user_id=current_user.id,
            org_id=str(org_id),
            todo_id=str(todo_id),
        )
    return await _render(request, session, current_user, repo, org)


@router.delete("/{todo_id}", response_class=HTMLResponse)
async def delete_todo(
    request: Request,
    bg: BackgroundTasks,
    todo_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    org_id: CurrentOrg,
):
    todo = await repo.get(todo_id)
    if todo:
        await repo.delete(todo)
        record_audit_event(
            bg,
            level="info",
            event="todo.deleted",
            user_id=current_user.id,
            org_id=str(org_id),
            todo_id=str(todo_id),
        )
    return await _render(request, session, current_user, repo, org)


@router.put("/{todo_id}/position", response_class=HTMLResponse)
async def move_todo(
    request: Request,
    todo_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
):
    body = await request.json()
    above_id = uuid.UUID(body["above_id"]) if body.get("above_id") else None
    await repo.move_above(todo_id, above_id)
    return await _render(request, session, current_user, repo, org)
