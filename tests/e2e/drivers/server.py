"""In-process hypercorn server for browser e2e tests.

Runs the app on a daemon-thread event loop so the test and the app share memory
(enables monkeypatching). Single responsibility: own the server lifecycle so the
browser substrate only orchestrates it.
"""

import asyncio
import socket
import time

from hypercorn.asyncio import serve
from hypercorn.config import Config

from apps.main import host
from tests.e2e.drivers.background_loop import BackgroundLoop

app = host.app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _make_event() -> asyncio.Event:
    return asyncio.Event()


class InProcessServer:
    def __init__(self) -> None:
        self._bg: BackgroundLoop | None = None
        self._shutdown: asyncio.Event | None = None
        self._server_future = None
        self._port: int | None = None

    def start(self) -> str:
        """Launch the server on a free port and return its base URL."""
        self._port = _free_port()
        self._bg = BackgroundLoop()
        self._bg.start()
        config = Config()
        config.bind = [f"127.0.0.1:{self._port}"]
        config.accesslog = config.errorlog = None
        self._shutdown = self._bg.run(_make_event())
        self._server_future = self._bg.submit(
            serve(app, config, shutdown_trigger=self._shutdown.wait)
        )
        self._wait_for_server()
        return f"http://127.0.0.1:{self._port}"

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
