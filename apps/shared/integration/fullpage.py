"""Fullpage context assembly — ownerless infra (peer of EventBus / Host).

A full HTML page's template context is composed of *slices*, each owned by the app
that knows it. An app registers a *fullpage provider* at its ``mount()`` via
:meth:`~apps.shared.integration.host.Host.register_fullpage_provider`, passing a ``name``, the
raw keys its function returns, and the function itself — the collector namespaces each key as
``f"{name}_{key}"`` (name ``profile`` declaring ``handle`` lands in the context as
``profile_handle``). Keys stay flat — no nested sub-dicts — so templates read
``{{ profile_handle }}``. A namespaced key colliding with another provider's, or with the
context's own seeded keys, is rejected at registration — see
:meth:`~apps.shared.integration.host.Host.register_fullpage_provider`.

A provider that raises is isolated and logged; the rest of the page still renders. A chunk
returning a key it never declared still logs and overwrites here — the mount-time check only
catches what was declared. A route's own page extra (``**extra``) is unprefixed, so it is
refused when it collides with a provider's declared, namespaced key or with the host's own
``nav_items`` — checked against what each provider declared at mount, before any provider
runs (``user`` cannot collide this way — see :func:`fullpage_context`).

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

from apps.shared.integration.host import RESERVED_FULLPAGE_KEYS, host

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
    docstring for the namespacing, collision and provider-isolation rules. A page extra named
    like a provider's declared key, or like the host's own ``nav_items``, is refused rather
    than silently overriding it — checked against what each provider declared at mount, before
    any provider runs. ``user`` cannot collide the same way: it is this function's own named
    parameter, so a ``user=`` extra fails on a duplicate-argument ``TypeError`` before the body
    ever runs.
    """
    owner_by_key: dict[str, str] = {"nav_items": "(host)"}
    for provider in host.fullpage_providers:
        for key in provider.keys:
            owner_by_key[f"{provider.name}_{key}"] = provider.name
    for key in extra:
        if key in owner_by_key:
            raise ValueError(f"page extra {key!r} collides with the {owner_by_key[key]} slice")

    ctx: dict = {"user": user, "nav_items": sorted(host.nav_items, key=lambda i: i.order)}
    # Kept identical to RESERVED_FULLPAGE_KEYS so a provider mount-time check protects
    # against exactly the keys seeded here.
    assert set(ctx) == RESERVED_FULLPAGE_KEYS
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
