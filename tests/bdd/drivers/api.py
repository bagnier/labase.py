import asyncio

import httpx

from app.main import app
from tests.bdd.drivers.base import BaseDriver


class ApiDriver(BaseDriver):
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: httpx.AsyncClient | None = None
        self._response: httpx.Response | None = None

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

    def login(self, email: str, password: str) -> None:
        self._response = self._run(
            self._c.post("/auth/login", data={"email": email, "password": password})
        )

    def visit(self, path: str) -> None:
        self._response = self._run(self._c.get(path))

    def assert_page_accessible(self, path: str, contains: str) -> None:
        resp = self._run(self._c.get(path))
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert contains in resp.text, f"'{contains}' not found in response"

    def assert_text(self, text: str) -> None:
        assert self._response is not None
        assert text in self._response.text, f"'{text}' not found in:\n{self._response.text[:500]}"

    def assert_unauthorized(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 401, f"Expected 401, got {self._response.status_code}"

    def assert_redirected_to_login(self) -> None:
        assert self._response is not None
        assert self._response.status_code in (301, 302, 307, 308), (
            f"Expected redirect, got {self._response.status_code}"
        )

    def assert_page_loaded(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 200, f"Expected 200, got {self._response.status_code}"

    def assert_login_rejected(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 401, f"Expected 401, got {self._response.status_code}"
