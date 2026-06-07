import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from supabase_auth import User

from app.auth.infra.dependencies import get_current_user
from app.shared.database import get_session
from app.shared.templates import templates
from app.todo.domain.models import TodoRead
from app.todo.infra.repository import TodoRepository

router = APIRouter(prefix="/todos", tags=["todo"])


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


@router.get("", response_class=HTMLResponse)
async def todo_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    repo = TodoRepository(session)
    todos = await repo.list_for_user(uuid.UUID(current_user.id))
    if _wants_json(request):
        return JSONResponse([TodoRead.model_validate(t).model_dump(mode="json") for t in todos])
    return templates.TemplateResponse(
        request, "todo/list.html", {"user": current_user, "todos": todos}
    )


@router.post("", response_class=HTMLResponse)
async def add_todo(
    request: Request,
    title: str = Form(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    repo = TodoRepository(session)
    await repo.add(uuid.UUID(current_user.id), title)
    todos = await repo.list_for_user(uuid.UUID(current_user.id))
    if _wants_json(request):
        return JSONResponse([TodoRead.model_validate(t).model_dump(mode="json") for t in todos])
    return templates.TemplateResponse(
        request, "todo/list.html", {"user": current_user, "todos": todos}
    )


@router.patch("/{todo_id}", response_class=HTMLResponse)
async def patch_todo(
    request: Request,
    todo_id: uuid.UUID,
    done: bool | None = Form(default=None),
    title: str | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    repo = TodoRepository(session)
    todo = await repo.get(todo_id, uuid.UUID(current_user.id))
    if todo and done is not None and todo.done != done:
        await repo.toggle_done(todo)
    if todo and title is not None:
        await repo.set_title(todo, title)
    todos = await repo.list_for_user(uuid.UUID(current_user.id))
    if _wants_json(request):
        return JSONResponse([TodoRead.model_validate(t).model_dump(mode="json") for t in todos])
    return templates.TemplateResponse(
        request, "todo/list.html", {"user": current_user, "todos": todos}
    )


@router.delete("/{todo_id}", response_class=HTMLResponse)
async def delete_todo(
    request: Request,
    todo_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    repo = TodoRepository(session)
    todo = await repo.get(todo_id, uuid.UUID(current_user.id))
    if todo:
        await repo.delete(todo)
    todos = await repo.list_for_user(uuid.UUID(current_user.id))
    if _wants_json(request):
        return JSONResponse([TodoRead.model_validate(t).model_dump(mode="json") for t in todos])
    return templates.TemplateResponse(
        request, "todo/list.html", {"user": current_user, "todos": todos}
    )


@router.post("/reorder")
async def reorder_todos(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    body = await request.json()
    todo_id = uuid.UUID(body["id"])
    above_id = uuid.UUID(body["above_id"]) if body.get("above_id") else None
    repo = TodoRepository(session)
    await repo.move_above(uuid.UUID(current_user.id), todo_id, above_id)
    todos = await repo.list_for_user(uuid.UUID(current_user.id))
    if _wants_json(request):
        return JSONResponse([TodoRead.model_validate(t).model_dump(mode="json") for t in todos])
    return templates.TemplateResponse(
        request, "todo/list.html", {"user": current_user, "todos": todos}
    )
