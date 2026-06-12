import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import get_current_user
from app.auth.infra.session import get_rls_session
from app.organizations.infra.context import get_current_org
from app.shared.http.templates import templates
from app.shared.observability.audit import record_audit_event
from app.todo.domain.models import TodoRead
from app.todo.infra.repository import TodoRepository

router = APIRouter(prefix="/todos", tags=["todo"])


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _html_template(request: Request) -> str:
    return "todo/_list_fragment.html" if _is_htmx(request) else "todo/list.html"


def _template_ctx(request: Request, current_user: object, todos: list) -> dict:
    org_slug = request.path_params.get("org_slug", "")
    return {"user": current_user, "todos": todos, "org_slug": org_slug}


@router.get("", response_class=HTMLResponse)
async def todo_list(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
    org_id: uuid.UUID = Depends(get_current_org),
):
    repo = TodoRepository(session)
    todos = await repo.list_for_org(org_id)
    if _wants_json(request):
        return JSONResponse([TodoRead.model_validate(t).model_dump(mode="json") for t in todos])
    return templates.TemplateResponse(
        request, _html_template(request), _template_ctx(request, current_user, todos)
    )


@router.post("", response_class=HTMLResponse)
async def add_todo(
    request: Request,
    bg: BackgroundTasks,
    title: str = Form(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
    org_id: uuid.UUID = Depends(get_current_org),
):
    repo = TodoRepository(session)
    todo = await repo.add(uuid.UUID(current_user.id), org_id, title)
    record_audit_event(
        bg,
        level="info",
        event="todo.created",
        user_id=current_user.id,
        org_id=str(org_id),
        todo_id=str(todo.id),
    )
    todos = await repo.list_for_org(org_id)
    if _wants_json(request):
        return JSONResponse([TodoRead.model_validate(t).model_dump(mode="json") for t in todos])
    return templates.TemplateResponse(
        request, _html_template(request), _template_ctx(request, current_user, todos)
    )


@router.patch("/{todo_id}", response_class=HTMLResponse)
async def patch_todo(
    request: Request,
    todo_id: uuid.UUID,
    done: bool | None = Form(default=None),
    title: str | None = Form(default=None),
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
    org_id: uuid.UUID = Depends(get_current_org),
):
    repo = TodoRepository(session)
    todo = await repo.get(todo_id, org_id)
    if todo and done is not None and todo.done != done:
        await repo.toggle_done(todo)
    if todo and title is not None:
        await repo.set_title(todo, title)
    todos = await repo.list_for_org(org_id)
    if _wants_json(request):
        return JSONResponse([TodoRead.model_validate(t).model_dump(mode="json") for t in todos])
    return templates.TemplateResponse(
        request, _html_template(request), _template_ctx(request, current_user, todos)
    )


@router.delete("/{todo_id}", response_class=HTMLResponse)
async def delete_todo(
    request: Request,
    bg: BackgroundTasks,
    todo_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
    org_id: uuid.UUID = Depends(get_current_org),
):
    repo = TodoRepository(session)
    todo = await repo.get(todo_id, org_id)
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
    todos = await repo.list_for_org(org_id)
    if _wants_json(request):
        return JSONResponse([TodoRead.model_validate(t).model_dump(mode="json") for t in todos])
    return templates.TemplateResponse(
        request, _html_template(request), _template_ctx(request, current_user, todos)
    )


@router.post("/reorder")
async def reorder_todos(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
    org_id: uuid.UUID = Depends(get_current_org),
):
    body = await request.json()
    todo_id = uuid.UUID(body["id"])
    above_id = uuid.UUID(body["above_id"]) if body.get("above_id") else None
    repo = TodoRepository(session)
    await repo.move_above(org_id, todo_id, above_id)
    todos = await repo.list_for_org(org_id)
    if _wants_json(request):
        return JSONResponse([TodoRead.model_validate(t).model_dump(mode="json") for t in todos])
    return templates.TemplateResponse(
        request, _html_template(request), _template_ctx(request, current_user, todos)
    )
