"""The contribution registry, keyed by query type
(AGENTS: a contribution is pulled, and a failing contributor is skipped).

Mount registers providers on ``host.contribs``, which is :data:`contribs` in production; runtime
code collects on :data:`contribs` directly.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog

log = structlog.get_logger(__name__)

Q = TypeVar("Q")


class Contribs:
    """Type-keyed registry of contribution providers, dispatched by the query's exact type."""

    def __init__(self) -> None:
        self._providers: dict[type, list[Callable[[Any], Awaitable[object]]]] = defaultdict(list)

    def provide(self, query_type: type[Q], provider: Callable[[Q], Awaitable[object]]) -> None:
        self._providers[query_type].append(provider)

    def providers(self, query_type: type) -> tuple[Callable[[Any], Awaitable[Any]], ...]:
        """For a caller that needs no log-and-skip (auth's ``ApiKeyQuery``), and for tests."""
        return tuple(self._providers.get(query_type, ()))

    async def collect(self, query: object) -> list[Any]:
        """Run every provider of the query's exact type, in turn; one that raises is logged as a
        bug and skipped.

        Providers share the query's session: each runs in a savepoint, so its SQL error does not
        abort the caller's transaction.
        """
        session = getattr(query, "session", None)
        results: list[Any] = []
        for provider in self._providers[type(query)]:
            try:
                if session is None:
                    results.append(await provider(query))
                else:
                    async with session.begin_nested():
                        results.append(await provider(query))
            except Exception:
                log.exception(
                    "query.provider_failed",
                    provider=repr(provider),
                    query_type=type(query).__name__,
                )
        return results


contribs = Contribs()
