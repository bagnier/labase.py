"""Technical substrate to execute browser (e2e) tests via Playwright.

Owns the app subprocess lifecycle, the Playwright page, the deterministic clock
(driven through the test-only endpoint), HTML assertions and HTMX interaction
helpers. Feature mixins inherit this; the concrete BrowserDriver assembles them.
No typing Protocol: this base *is* the shared contract.
"""

import atexit
import contextlib
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import Browser, Page, Response, sync_playwright

from tests.e2e import cleanup


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# One pidfile per started server: if a run dies without calling stop() (SIGKILL, crash),
# the next run finds and kills orphaned servers via _reap_stale_servers().
_PID_DIR = Path(tempfile.gettempdir()) / "labase-e2e-servers"


def _cmdline(pid: int) -> str:
    out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True)
    return out.stdout


def _reap_stale_servers() -> None:
    if not _PID_DIR.is_dir():
        return
    for pidfile in _PID_DIR.glob("*.pid"):
        try:
            pid = int(pidfile.read_text().strip())
        except ValueError:
            pidfile.unlink(missing_ok=True)
            continue
        # Verify the command line before killing: the pid may have been reused.
        if "hypercorn app.main:app" in _cmdline(pid):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(pid, signal.SIGKILL)
        pidfile.unlink(missing_ok=True)


class BrowserBase:
    def __init__(self) -> None:
        self._base_url: str = os.environ.get("APP_URL", "")
        self._server: subprocess.Popen | None = None
        self._pidfile: Path | None = None
        self._pw = None
        self._browser = None
        self._context = None
        self._page: Page | None = None
        self._last_response: Response | None = None
        self._last_registered_email: str | None = None
        self._active_org_handle: str = ""
        self._primary_email: str = ""
        self._secondary_browser_contexts: dict = {}
        self._acting_as_email: str = ""
        self._primary_context_backup = None

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        if not self._base_url:
            _reap_stale_servers()
            port = _free_port()
            self._base_url = f"http://127.0.0.1:{port}"
            # start_new_session: the server and its multiprocessing workers form their
            # own process group — stop() can kill the entire group via killpg
            # (terminate() alone left the worker holding the postgres pool alive).
            self._server = subprocess.Popen(
                [sys.executable, "-m", "hypercorn", "app.main:app", "--bind", f"127.0.0.1:{port}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            _PID_DIR.mkdir(exist_ok=True)
            self._pidfile = _PID_DIR / f"{self._server.pid}.pid"
            self._pidfile.write_text(str(self._server.pid))
            atexit.register(self._stop_server)
            self._wait_for_server()

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._open_context()

    def _open_context(self) -> None:
        assert self._browser
        self._context = self._browser.new_context()
        self._page = self._context.new_page()

    def _wait_for_server(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(
                    ("127.0.0.1", int(self._base_url.split(":")[-1])), timeout=0.5
                ):
                    return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError(f"Server did not start within {timeout}s")

    def stop(self) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        self._stop_server()
        atexit.unregister(self._stop_server)

    def _stop_server(self) -> None:
        if not self._server:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(self._server.pid, signal.SIGTERM)
        try:
            self._server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(self._server.pid, signal.SIGKILL)
            self._server.wait()
        if self._pidfile:
            self._pidfile.unlink(missing_ok=True)
            self._pidfile = None
        self._server = None

    def reset_session(self) -> None:
        for ctx in self._secondary_browser_contexts.values():
            ctx.close()
        self._secondary_browser_contexts = {}
        if self._context:
            self._context.close()
        self._open_context()
        self._last_response = None
        self._active_org_handle = ""
        self._primary_email = ""
        self._acting_as_email = ""
        self._primary_context_backup = None
        self._org_list_response = None  # type: ignore[attr-defined]

    @property
    def _p(self) -> Page:
        assert self._page
        return self._page

    @property
    def _b(self) -> Browser:
        assert self._browser
        return self._browser

    # ── test isolation ─────────────────────────────────────────────────────────
    def setup_test(self) -> None:
        """No transaction wrapping: the app runs in its own process."""

    def teardown_test(self) -> None:
        """Truncate app tables. Feature mixins extend this (via super())."""
        cleanup.truncate_app_tables()

    # ── HTMX interaction helpers (real button clicks) ──────────────────────────
    def _arm_dialogs(self, page) -> None:
        """Auto-accept hx-confirm dialogs, once per page."""
        armed = getattr(self, "_dialogs_armed", None)
        if armed is None:
            armed = self._dialogs_armed = set()
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

    # ── cross-feature methods (real impl provided by feature mixins) ───────────
    def sign_in(self, email: str, password: str) -> None: ...

    def delete_todo(self, title: str) -> None: ...

    def rename_todo(self, title: str, new_title: str) -> None: ...
