"""A single asyncio event loop running in a daemon thread.

Owned once and reused by both e2e substrates: the API driver runs coroutines on
it (ASGI calls over httpx), the browser driver schedules the hypercorn server on
it. There is exactly one launch/stop mechanism for the in-process server, here.
"""

import asyncio
import threading


class BackgroundLoop:
    """Running from construction to ``stop()`` — there is no loop that exists without running,
    so no reader has to ask whether it started."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro):
        """Run a coroutine to completion and return its result (blocks the caller)."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def submit(self, coro):
        """Schedule a coroutine without waiting; returns a concurrent.futures.Future."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def call_soon(self, fn, *args) -> None:
        self._loop.call_soon_threadsafe(fn, *args)

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
