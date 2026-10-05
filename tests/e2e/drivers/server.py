"""The browser driver's in-process hypercorn server: test and app share memory, so
monkeypatching reaches the app."""

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
    """Both loopbacks: ``localhost`` (the WebAuthn rp_id) may resolve to either."""
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
    def __init__(self, port: int | None = None) -> None:
        """Serve on `port`, or a free one, until ``stop()``; at ``localhost``, the WebAuthn
        ``rp_id``."""
        self._port = port or _free_port()
        self._bg = BackgroundLoop()
        config = Config()
        config.bind = _loopback_binds(self._port)
        config.accesslog = config.errorlog = None
        self._shutdown = self._bg.run(_make_event())
        self._server_future = self._bg.submit(
            # hypercorn's TypedDict scopes against starlette's mapping: fine at runtime only.
            serve(cast(Framework, app), config, shutdown_trigger=self._shutdown.wait)
        )
        self._wait_for_server()
        self.base_url = f"http://localhost:{self._port}"

    def run(self, coro):
        """Run a coroutine on the server's loop, where the app's engines live."""
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
        self._bg.call_soon(self._shutdown.set)
        self._server_future.result(timeout=10)
        self._bg.stop()
