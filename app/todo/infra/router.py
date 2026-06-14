import uuid

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.organizations.domain.models import Organization
from app.shared.dependencies import CurrentOrg, CurrentOrgModel, CurrentUser, RlsSession
from app.shared.http import render_list
from app.shared.observability.audit import record_audit_event
from app.todo.domain.models import TodoRead
from app.todo.infra.repository import TodoRepository

router = APIRouter(prefix="/todos", tags=["todo"])


def _render(request: Request, current_user: object, todos: list, org: Organization) -> Response:
    return render_list(
        request,
        fragment="todo/_list_fragment.html",
        full="todo/list.html",
        items_key="todos",
        schema=TodoRead,
        items=todos,
        user=current_user,
        org=org,
    )


@router.get("", response_class=HTMLResponse)
async def todo_list(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
):
    repo = TodoRepository(session, org_id)
    todos = await repo.all()
    return _render(request, current_user, todos, org)


@router.post("", response_class=HTMLResponse)
async def add_todo(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
    title: str = Form(...),
):
    repo = TodoRepository(session, org_id)
    todo = await repo.add(uuid.UUID(current_user.id), title)
    record_audit_event(
        bg,
        level="info",
        event="todo.created",
        user_id=current_user.id,
        org_id=str(org_id),
        todo_id=str(todo.id),
    )
    todos = await repo.all()
    return _render(request, current_user, todos, org)


@router.patch("/{todo_id}", response_class=HTMLResponse)
async def patch_todo(
    request: Request,
    todo_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
    done: bool | None = Form(default=None),
    title: str | None = Form(default=None),
):
    repo = TodoRepository(session, org_id)
    todo = await repo.get(todo_id)
    if todo is None:
        raise HTTPException(404)
    if done is not None:
        todo.done = done
    if title is not None:
        todo.title = title
    await repo.save(todo)
    todos = await repo.all()
    return _render(request, current_user, todos, org)


@router.delete("/{todo_id}", response_class=HTMLResponse)
async def delete_todo(
    request: Request,
    bg: BackgroundTasks,
    todo_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
):
    repo = TodoRepository(session, org_id)
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
    todos = await repo.all()
    return _render(request, current_user, todos, org)


@router.post("/reorder")
async def reorder_todos(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
):
    body = await request.json()
    todo_id = uuid.UUID(body["id"])
    above_id = uuid.UUID(body["above_id"]) if body.get("above_id") else None
    repo = TodoRepository(session, org_id)
    await repo.move_above(todo_id, above_id)
    todos = await repo.all()
    return _render(request, current_user, todos, org)
