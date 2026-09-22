"""Type-keyed contribution registry — the *pull* half of inter-app collaboration.

Where :mod:`apps.shared.events.bus` carries *events* (a fact happened, fan out to reactions), this
carries *contributions*: a host asks "who contributes to this query?" and aggregates the
answers. It is not pub/sub — it is a registry of providers (an extension point), declared at
mount and read synchronously on the request path:

- ``provide(query_type, provider)`` — register a contributor for a query type.
- ``collect(query)`` — run every provider for the query's exact type, isolate failures
  (log + skip), return the successful results.

The two halves have opposite failure policies on purpose: a missing/failing *contribution*
must never break the page that gathers it (a dashboard renders without the down app's card),
whereas an *event* handler failure is a real fault the emitter may need to compensate for.

Runtime collectors import the process-wide :data:`contribs` singleton directly — a focused
collaborator, not the whole :class:`~apps.shared.integration.host.Host`. Mount wires providers onto
``host.contribs``, which *is* this same ``contribs`` in production, so registration and
dispatch share one registry.
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
        """The providers registered for a query type — read-only, so declaration-level tests can
        ask the mounted registry instead of grepping source, or (as auth's own resolution of
        ``ApiKeyQuery`` does) call each in turn without ``collect``'s log-and-skip policy."""
        return tuple(self._providers.get(query_type, ()))

    async def collect(self, query: object) -> list[Any]:
        """Run every provider for this query type; log and skip failing providers.

        A provider failure is a bug: ``log.exception`` feeds it to the capture seam, which folds
        it into an issue (``query_type`` names the query so it survives into the issue's
        context). The drain delivers under a reentrancy guard, so a tracker that is itself a
        failing provider here cannot recurse.

        Providers share the caller's session (every query type carries one), so a provider's own
        SQL error aborts that shared transaction — a savepoint around each call confines the
        abort to it, leaving later providers and the caller's own queries unaffected: a down app
        can't break the page.
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


# Process-wide singleton. Runtime code collects on this directly; the production Host is built with
# ``contribs=contribs``, so its mount-time ``.provide(...)`` registrations land here too.
contribs = Contribs()
