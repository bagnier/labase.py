import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

import httpx

from app.main import app

_transport = httpx.ASGITransport(app=app)
BASE_URL = "http://testserver"

T = TypeVar("T")


def get_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=_transport, base_url=BASE_URL, follow_redirects=False)


def run(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.get_event_loop().run_until_complete(coro)
