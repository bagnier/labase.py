"""Fullpage context assembly — ownerless infra (peer of EventBus / Host).

A full HTML page's template context is composed of *slices*, each owned by the app
that knows it. An app registers a *fullpage provider* at its ``mount()`` via
:meth:`~apps.shared.integration.host.Host.register_fullpage_provider`, passing a ``name`` and a
function that returns raw keys — the collector namespaces them as ``f"{name}_{key}"``
(name ``profile`` returning ``handle`` lands in the context as ``profile_handle``).
Keys stay flat — no nested sub-dicts — so templates read ``{{ profile_handle }}``.

If a provider's namespaced key collides with one already in the context, the merge
logs and overwrites. A provider that raises is isolated and logged; the rest of the
page still renders.

No global render hook injects data silently — a Jinja "context processor" or ASGI
middleware would, and that is proscribed by the *Page composition* principle. Routes
call :func:`fullpage_context` explicitly, only on full pages (not HTMX fragments).

Current providers (grep ``register_fullpage_provider`` to confirm):

==================  =======  =======================================
key                 name     provider
==================  =======  =======================================
``nav_items``       (host)   seeded here from ``host.nav_items``
``user``            (host)   added by :func:`fullpage_context`
``profile_handle``  profile  ``apps.profile.contract.fullpage``
``org_nav``         org      ``apps.organizations.contract.fullpage``
==================  =======  =======================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.integration.host import host

if TYPE_CHECKING:
    from apps.auth.contract.user import AuthenticatedUser

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class FullpageQuery:
    """Passed to each provider; carries the request session and the current user."""

    session: AsyncSession
    user: AuthenticatedUser | None


async def fullpage_context(
    session: AsyncSession, user: AuthenticatedUser | None, **extra: object
) -> dict:
    """Full template context for a page: nav + provider slices + user + page extras.

    Called explicitly by routes, on full pages only (never HTMX fragments) — see the module
    docstring for the namespacing, collision and provider-isolation rules.
    """
    ctx: dict = {"user": user, "nav_items": sorted(host.nav_items, key=lambda i: i.order)}
    query = FullpageQuery(session, user)
    for provider in host.fullpage_providers:
        try:
            chunk = await provider.fn(query)
        except Exception:
            log.exception("page.provider_failed", provider=provider.name)
            continue
        for key, value in chunk.items():
            full_key = f"{provider.name}_{key}"
            if full_key in ctx:
                log.warning("page.overwrite", key=full_key, provider=provider.name)
            ctx[full_key] = value
    return {**ctx, **extra}
