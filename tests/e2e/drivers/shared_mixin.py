import datetime

from app.shared import clock
from tests.e2e.drivers.protocols import ApiProtocol, BrowserProtocol


def _parse(date: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(date).replace(tzinfo=datetime.UTC)


class SharedApiMixin(ApiProtocol):
    # API driver runs the app in-process: monkeypatch clock.now directly.
    def _pin(self, value: datetime.datetime) -> None:
        if not hasattr(self, "_real_now"):
            self._real_now = clock.now
        clock.now = lambda: value  # ty: ignore[invalid-assignment]
        self._pinned = True

    def set_current_date(self, date: str) -> None:
        self._pin(_parse(date))

    def ensure_clock(self, default_iso: str) -> None:
        """Pin a deterministic clock if no scenario step has set one yet."""
        if not getattr(self, "_pinned", False):
            self.set_current_date(default_iso)

    def advance_days(self, days: int) -> None:
        self._pin(clock.now() + datetime.timedelta(days=days))

    def _restore_clock(self) -> None:
        if hasattr(self, "_real_now"):
            clock.now = self._real_now  # ty: ignore[invalid-assignment]
        self._pinned = False

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
    # Browser driver runs the app in a subprocess: drive its clock via the
    # test-only endpoint, mirroring the pinned value locally for advance/_today.
    def _push_clock(self) -> None:
        assert self._context
        value: datetime.datetime | None = getattr(self, "_clock_value", None)
        self._context.request.post(
            f"{self._base_url}/__test__/clock",
            data={"now": value.isoformat() if value else None},
        )

    def set_current_date(self, date: str) -> None:
        self._clock_value = _parse(date)
        self._push_clock()

    def ensure_clock(self, default_iso: str) -> None:
        if getattr(self, "_clock_value", None) is None:
            self.set_current_date(default_iso)

    def advance_days(self, days: int) -> None:
        self._clock_value = getattr(self, "_clock_value", None) or datetime.datetime.now(
            datetime.UTC
        )
        self._clock_value += datetime.timedelta(days=days)
        self._push_clock()

    def _restore_clock(self) -> None:
        self._clock_value = None
        self._push_clock()

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

    # ── HTMX interaction helpers (real button clicks) ──────────────────────────

    def _arm_dialogs(self, page) -> None:
        """Auto-accept hx-confirm dialogs, once per page."""
        armed = getattr(self, "_dialogs_armed", None)
        if armed is None:
            armed = self._dialogs_armed = set()  # type: ignore[attr-defined]
        if id(page) not in armed:
            page.on("dialog", lambda d: d.accept())
            armed.add(id(page))

    def _click_and_capture(self, page, selector: str, method: str, path_token: str):
        """Click a control and return the HTMX response it triggers."""
        self._arm_dialogs(page)
        with page.expect_response(
            lambda r: path_token in r.url and r.request.method == method
        ) as info:
            page.click(selector)
        return info.value
