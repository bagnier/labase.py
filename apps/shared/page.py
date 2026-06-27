"""Page context assembly — ownerless infra (peer of EventBus / Host).

A full HTML page's template context is composed of *slices*, each owned by the app
that knows it. An app registers a *page context provider* at its ``mount()`` via
:meth:`~apps.shared.host.Host.register_page_context`, declaring **the exact keys it
injects** — so the page's context shape is documented at the registration site, not
discovered at runtime.

The ``namespace`` is the key prefix the slice owns: every key it injects must start
with ``f"{namespace}_"`` (namespace ``profile`` → key ``profile_handle``, namespace
``org`` → key ``org_nav``). Keys stay flat — no nested sub-dicts — so templates
read ``{{ profile_handle }}``. ``user`` and ``nav_items`` are reserved by the collector.

Two guarantees keep the namespace clean:

- **Startup.** ``register_page_context`` rejects a mis-prefixed, reserved, or
  already-owned key — collisions fail fast when the app mounts.
- **Runtime.** The merge skips (and logs) any undeclared or clobbering key a provider
  returns, and isolates a provider that raises.

No global render hook injects data silently — a Jinja "context processor" or ASGI
middleware would, and that is proscribed by the *Page composition* principle. Routes
call these functions explicitly: full pages use :func:`fullpage_context`, HTMX
fragments don't.

Current slices (grep ``register_page_context`` to confirm):

==================  ===========  =======================================
key                 namespace    provider
==================  ===========  =======================================
``nav_items``       (host)       seeded here from ``host.nav_items``
``user``            (collector)  added by :func:`fullpage_context`
``profile_handle``  profile      ``apps.profile.contract.shell``
``org_nav`` org          ``apps.organizations.contract.shell``
==================  ===========  =======================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.host import host

if TYPE_CHECKING:
    from apps.auth.contract.user import AuthenticatedUser

log = structlog.get_logger("labase.shared.page")


@dataclass(frozen=True)
class PageContextQuery:
    """Passed to each provider; carries the request session and the current user."""

    session: AsyncSession
    user: AuthenticatedUser | None


async def shell_context(session: AsyncSession, user: AuthenticatedUser | None) -> dict:
    """The collected page slices (handle, orgs, nav) — without the ``user`` key.

    Used directly by HTMX-aware routes that only merge the shell on full pages.
    Each provider's return is checked against its declared keys: undeclared or
    clobbering keys are skipped and logged.
    """
    ctx: dict = {"nav_items": sorted(host.nav_items, key=lambda i: i.order)}
    query = PageContextQuery(session, user)
    for provider in host.page_providers:
        try:
            chunk = await provider.fn(query)
        except Exception:
            log.exception("page.provider_failed", namespace=provider.namespace)
            continue
        for key, value in chunk.items():
            if key not in provider.keys:
                log.warning("page.undeclared_key", namespace=provider.namespace, key=key)
                continue
            if key in ctx:
                log.warning("page.key_collision", namespace=provider.namespace, key=key)
                continue
            ctx[key] = value
    return ctx


async def fullpage_context(
    session: AsyncSession, user: AuthenticatedUser | None, **extra: object
) -> dict:
    """Full template context for an authenticated page: shell + user + page extras."""
    return {"user": user, **await shell_context(session, user), **extra}
