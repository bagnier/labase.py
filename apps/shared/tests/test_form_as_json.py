"""``FormAsJson`` (AGENTS: a form is JSON at the door)."""

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from apps.shared.http.form import FormAsJson


class Note(BaseModel):
    title: str
    done: bool = False


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(FormAsJson)

    @app.post("/notes")
    async def add_note(note: Note, request: Request) -> JSONResponse:
        return JSONResponse(
            {"note": note.model_dump(), "content_type": request.headers["content-type"]}
        )

    @app.post("/uploads")
    async def upload(file: UploadFile) -> JSONResponse:
        return JSONResponse({"filename": file.filename, "size": len(await file.read())})

    return app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_a_form_reaches_the_handler_as_its_declared_body(client):
    """Strings coerce ("on" is a checkbox's true); a blank value stays a value."""
    response = await client.post("/notes", data={"title": "", "done": "on"})

    assert (response.status_code, response.json()) == (
        200,
        {"note": {"title": "", "done": True}, "content_type": "application/json"},
    )


@pytest.mark.asyncio
async def test_a_repeated_key_keeps_its_last_value(client):
    """A hidden ``done=false`` before the box; the ticked box's ``done=true`` wins."""
    form = {"content-type": "application/x-www-form-urlencoded"}
    unticked = await client.post("/notes", content="title=t&done=false", headers=form)
    ticked = await client.post("/notes", content="title=t&done=false&done=true", headers=form)

    assert (unticked.json()["note"]["done"], ticked.json()["note"]["done"]) == (False, True)


@pytest.mark.asyncio
async def test_a_json_body_passes_through_untouched(client):
    response = await client.post("/notes", json={"title": "x"})

    assert (response.status_code, response.json()["note"]) == (200, {"title": "x", "done": False})


@pytest.mark.asyncio
async def test_a_multipart_upload_is_left_alone(client):
    response = await client.post("/uploads", files={"file": ("a.txt", b"hello")})

    assert (response.status_code, response.json()) == (200, {"filename": "a.txt", "size": 5})


@pytest.mark.asyncio
async def test_the_schema_describes_the_form_as_the_json_body_it_becomes():
    schema = _app().openapi()

    body = schema["paths"]["/notes"]["post"]["requestBody"]["content"]

    assert body == {"application/json": {"schema": {"$ref": "#/components/schemas/Note"}}}
