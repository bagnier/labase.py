"""Type-keyed contribution registry — the *pull* half of inter-app collaboration.

Where :mod:`apps.shared.bus` carries *events* (a fact happened, fan out to reactions), this
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
collaborator, not the whole :class:`~apps.shared.host.Host`. Mount wires providers onto
``host.contribs``, which *is* this same ``contribs`` in production, so registration and
dispatch share one registry.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog

log = structlog.get_logger("labase.shared.contribs")

Q = TypeVar("Q")


class Contribs:
    """Type-keyed registry of contribution providers, dispatched by the query's exact type."""

    def __init__(self) -> None:
        self._providers: dict[type, list[Callable[[Any], Awaitable[object]]]] = defaultdict(list)

    def provide(self, query_type: type[Q], provider: Callable[[Q], Awaitable[object]]) -> None:
        self._providers[query_type].append(provider)

    async def collect(self, query: object) -> list[Any]:
        """Run every provider for this query type; log and skip failing providers.

        A provider failure is a bug: ``log.exception`` feeds it to the error tracker through the
        capture processor (``event_type`` names the failing query so it survives into the issue
        context). The capture drain runs recording under a reentrancy guard, so a tracker
        provider that itself fails here cannot recurse.
        """
        results: list[Any] = []
        for provider in self._providers[type(query)]:
            try:
                results.append(await provider(query))
            except Exception:
                log.exception(
                    "query.handler_failed",
                    handler=repr(provider),
                    event_type=type(query).__name__,
                )
        return results


# Process-wide singleton. Runtime code collects on this directly; the production Host is built
# with ``contribs=contribs`` so its mount-time ``.provide(...)`` registrations land here too.
contribs = Contribs()
