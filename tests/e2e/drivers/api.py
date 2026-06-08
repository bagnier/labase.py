import asyncio
import threading

import httpx

from app.auth.tests.driver_mixin import AuthApiMixin
from app.dashboard.tests.driver_mixin import DashboardApiMixin
from app.main import app
from app.todo.tests.driver_mixin import TodoApiMixin
from tests.e2e.drivers.shared_mixin import SharedApiMixin


class ApiDriver(AuthApiMixin, DashboardApiMixin, TodoApiMixin, SharedApiMixin):
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: httpx.AsyncClient | None = None
        self._response: httpx.Response | None = None
        self._last_registered_email: str | None = None

    def start(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=False,
        )

    def stop(self) -> None:
        if self._client and self._loop:
            asyncio.run_coroutine_threadsafe(self._client.aclose(), self._loop).result()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join()

    def _run(self, coro):
        assert self._loop
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    @property
    def _c(self) -> httpx.AsyncClient:
        assert self._client
        return self._client

    def reset_session(self) -> None:
        transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=False,
        )
