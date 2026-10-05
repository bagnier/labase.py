"""An event loop in a daemon thread, shared by both drivers: the API driver's calls, the browser
driver's server.
"""

import asyncio
import threading


class BackgroundLoop:
    """Runs from construction to ``stop()``."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def call_soon(self, fn, *args) -> None:
        self._loop.call_soon_threadsafe(fn, *args)

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
