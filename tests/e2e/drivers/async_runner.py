from collections.abc import Coroutine
from typing import Any, TypeVar

from tests.e2e.drivers.background_loop import BackgroundLoop

_T = TypeVar("_T")


class AsyncRunner:
    def __init__(self) -> None:
        self._bg = BackgroundLoop()

    def start(self) -> None:
        self._bg.start()

    def stop(self) -> None:
        self._bg.stop()

    def run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        return self._bg.run(coro)
