import asyncio

import httpx

from app.auth.tests.driver_mixin import AuthApiMixin
from app.dashboard.tests.driver_mixin import DashboardApiMixin
from app.main import app
from app.todo.tests.driver_mixin import TodoApiMixin
from tests.e2e.drivers.shared_mixin import SharedApiMixin


class ApiDriver(AuthApiMixin, DashboardApiMixin, TodoApiMixin, SharedApiMixin):
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: httpx.AsyncClient | None = None
        self._response: httpx.Response | None = None
        self._last_registered_email: str | None = None

    def start(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=False,
        )

    def stop(self) -> None:
        if self._client and self._loop:
            self._loop.run_until_complete(self._client.aclose())
        if self._loop:
            self._loop.close()

    def _run(self, coro):
        assert self._loop
        return self._loop.run_until_complete(coro)

    @property
    def _c(self) -> httpx.AsyncClient:
        assert self._client
        return self._client

    def reset_session(self) -> None:
        if self._client and self._loop:
            self._loop.run_until_complete(self._client.aclose())
        transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=False,
        )
