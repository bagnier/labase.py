import datetime

import app.shared.clock as _clock
from tests.e2e.drivers.protocols import ApiProtocol, BrowserProtocol


class SharedApiMixin(ApiProtocol):
    def set_current_date(self, date: str) -> None:
        fixed = datetime.datetime.fromisoformat(date).replace(tzinfo=datetime.timezone.utc)
        self._original_now = _clock.now
        _clock.now = lambda: fixed  # type: ignore[method-assign]

    def _restore_clock(self) -> None:
        if hasattr(self, "_original_now"):
            _clock.now = self._original_now
            del self._original_now

    def visit(self, path: str) -> None:
        self._response = self._run(self._c.get(path))

    def assert_page_accessible(self, path: str, contains: str) -> None:
        resp = self._run(self._c.get(path))
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert contains in resp.text, f"'{contains}' not found in response"

    def assert_text(self, text: str) -> None:
        assert self._response is not None
        assert text in self._response.text, f"'{text}' not found in:\n{self._response.text[:500]}"

    def assert_page_loaded(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 200, f"Expected 200, got {self._response.status_code}"


class SharedBrowserMixin(BrowserProtocol):
    def set_current_date(self, date: str) -> None:
        fixed = datetime.datetime.fromisoformat(date).replace(tzinfo=datetime.timezone.utc)
        _clock.now = lambda: fixed  # type: ignore[method-assign]

    def visit(self, path: str) -> None:
        self._last_response = self._p.goto(f"{self._base_url}{path}", wait_until="load")

    def assert_page_accessible(self, path: str, contains: str) -> None:
        self._p.goto(f"{self._base_url}{path}", wait_until="load")
        assert contains in self._p.content(), f"'{contains}' not found on {path}"

    def assert_text(self, text: str) -> None:
        assert text in self._p.content(), f"'{text}' not found in page content"

    def assert_page_loaded(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status == 200, f"Expected 200, got {self._last_response.status}"
