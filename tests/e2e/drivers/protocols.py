from typing import Any, Protocol

import httpx


class ApiProtocol(Protocol):
    _response: httpx.Response | None
    _last_registered_email: str | None

    def _run(self, coro: Any) -> Any: ...

    @property
    def _c(self) -> httpx.AsyncClient: ...

    def delete_todo(self, title: str) -> None: ...

    def rename_todo(self, title: str, new_title: str) -> None: ...


class BrowserProtocol(Protocol):
    _base_url: str
    _last_response: Any
    _last_registered_email: str | None
    _context: Any

    @property
    def _p(self) -> Any: ...

    def delete_todo(self, title: str) -> None: ...

    def rename_todo(self, title: str, new_title: str) -> None: ...
