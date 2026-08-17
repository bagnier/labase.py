"""In-process hypercorn server for browser e2e tests.

Runs the app on a daemon-thread event loop so the test and the app share memory
(enables monkeypatching). Single responsibility: own the server lifecycle so the
browser substrate only orchestrates it.
"""

import asyncio
import socket
import time
from typing import cast

from hypercorn.asyncio import serve
from hypercorn.config import Config
from hypercorn.typing import Framework

from apps.main import host
from tests.e2e.drivers.background_loop import BackgroundLoop

app = host.app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _loopback_binds(port: int) -> list[str]:
    """Both loopback sockets when the machine has them.

    The base URL says ``localhost`` (WebAuthn rp_id), and resolvers differ on
    whether that means ``::1`` or ``127.0.0.1`` — listening on both makes the
    URL work either way."""
    binds = [f"127.0.0.1:{port}"]
    try:
        with socket.socket(socket.AF_INET6) as s:
            s.bind(("::1", 0))
        binds.append(f"[::1]:{port}")
    except OSError:
        pass
    return binds


async def _make_event() -> asyncio.Event:
    return asyncio.Event()


class InProcessServer:
    def __init__(self) -> None:
        self._bg: BackgroundLoop | None = None
        self._shutdown: asyncio.Event | None = None
        self._server_future = None
        self._port: int | None = None

    def start(self, port: int | None = None) -> str:
        """Launch the server (on `port`, or a free one) and return its base URL.

        The URL says ``localhost`` (same socket) so the browser's origin domain
        matches the WebAuthn ``rp_id`` GoTrue pins; a pinned `port` listed in
        ``rp_origins`` is what lets ``navigator.credentials`` ceremonies verify
        in e2e (see the browser driver)."""
        self._port = port or _free_port()
        self._bg = BackgroundLoop()
        self._bg.start()
        config = Config()
        config.bind = _loopback_binds(self._port)
        config.accesslog = config.errorlog = None
        self._shutdown = self._bg.run(_make_event())
        self._server_future = self._bg.submit(
            # starlette types an ASGI scope as a loose mapping, hypercorn as precise TypedDicts;
            # a FastAPI app satisfies the protocol at runtime, not statically. Both checkers agree.
            serve(cast(Framework, app), config, shutdown_trigger=self._shutdown.wait)
        )
        self._wait_for_server()
        return f"http://localhost:{self._port}"

    def run(self, coro):
        """Run a coroutine on the server's event loop and return its result.

        The app's engines live on that loop; anything touching them (e.g. a
        TaskWorker tick) must run there too.
        """
        assert self._bg is not None, "run() before start()"
        return self._bg.submit(coro).result(timeout=30)

    def _wait_for_server(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self._port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError(f"Server did not start within {timeout}s")

    def stop(self) -> None:
        if not self._bg:
            return
        if self._shutdown:
            self._bg.call_soon(self._shutdown.set)
        if self._server_future:
            self._server_future.result(timeout=10)
        self._bg.stop()
        self._bg = None
        self._shutdown = None
        self._server_future = None
