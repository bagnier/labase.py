import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.auth.domain.service import AuthenticatedUser
from app.profile.contract.shell import shell_context
from app.shared.dependencies import CurrentOrg, CurrentOrgModel, CurrentUser, RlsSession
from app.shared.http import render_list, wants_full_page
from app.shared.observability.audit import record_audit_event
from app.todo.domain.models import TodoRead
from app.todo.infra.repository import TodoRepository


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
    title: str = Form(...),
):
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
    todo_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: TodoRepo,
    org: CurrentOrgModel,
    done: bool | None = Form(default=None),
    title: str | None = Form(default=None),
):
    todo = await repo.get(todo_id)
    if todo is None:
        raise HTTPException(404)
    if done is not None:
        todo.done = done
    if title is not None:
        todo.title = title
    await repo.save(todo)
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
