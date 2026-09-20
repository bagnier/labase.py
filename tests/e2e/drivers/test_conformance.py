"""The conformance check, on a schema of its own: what it lets through, what it names."""

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from tests.e2e.drivers.conformance import Conformance


class Item(BaseModel):
    id: int
    name: str


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/items", response_model=list[Item])
    async def items() -> JSONResponse:
        return JSONResponse([{"id": 1, "name": "a"}])

    @app.get("/{slug}/items/{item_id}", response_model=Item)
    async def item(slug: str, item_id: int) -> JSONResponse:
        return JSONResponse({"id": "not-a-number", "name": "a"})

    @app.get("/{slug}")
    async def page(slug: str) -> JSONResponse:
        return JSONResponse({"anything": "goes"})

    @app.get("/undeclared", responses={200: {"content": {"application/json": {}}}})
    async def undeclared() -> JSONResponse:
        return JSONResponse({"free": "form"})

    return app


async def _get(path: str):
    app = _app()
    conformance = Conformance(app.openapi())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get(path)
    conformance.check(response)
    return response.status_code


@pytest.mark.asyncio
async def test_an_answer_matching_its_schema_passes():
    assert await _get("/items") == 200


@pytest.mark.asyncio
async def test_an_answer_straying_from_its_schema_is_named_by_its_operation():
    """The most literal template wins the match — `/{slug}/items/{item_id}`, not `/{slug}` —
    and the message says which operation and which field."""
    with pytest.raises(AssertionError) as refused:
        await _get("/acme/items/7")

    assert str(refused.value) == (
        "GET /{slug}/items/{item_id} answered JSON that strays from its declared schema: "
        "['id']: 'not-a-number' is not of type 'integer'"
    )


@pytest.mark.asyncio
async def test_a_face_the_schema_leaves_blank_is_not_checked():
    assert await _get("/undeclared") == 200
