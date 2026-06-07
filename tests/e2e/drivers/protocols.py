from typing import Any, Protocol

import httpx


class ApiProtocol(Protocol):
    _response: httpx.Response | None
    _last_registered_email: str | None

    def _run(self, coro: Any) -> Any: ...

    @property
    def _c(self) -> httpx.AsyncClient: ...


class BrowserProtocol(Protocol):
    _base_url: str
    _last_response: Any
    _last_registered_email: str | None
    _context: Any

    @property
    def _p(self) -> Any: ...
