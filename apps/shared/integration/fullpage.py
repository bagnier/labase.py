"""A full page's template context, assembled from slices
(AGENTS: a page's context is assembled from slices its apps own).

An app registers a provider at mount with
:meth:`~apps.shared.integration.host.Host.register_fullpage_provider`, declaring its keys. Each key
is namespaced flat: provider ``profile`` returning ``handle`` gives ``{{ profile_handle }}``.
Collisions between declared keys are refused at registration; a provider that raises is logged
and skipped. Routes call :func:`fullpage_context` explicitly, on full pages only.

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
    session: AsyncSession
    user: AuthenticatedUser | None


async def fullpage_context(
    session: AsyncSession, user: AuthenticatedUser | None, **extra: object
) -> dict:
    """Nav, provider slices, ``user`` and the route's ``extra``.

    Raises ``ValueError`` when an extra is named like a declared slice key or ``nav_items``. A
    provider returning an undeclared key that collides is only logged.
    """
    owner_by_key: dict[str, str] = {"nav_items": "(host)"}
    for provider in host.fullpage_providers:
        for key in provider.keys:
            owner_by_key[f"{provider.name}_{key}"] = provider.name
    for key in extra:
        if key in owner_by_key:
            raise ValueError(f"page extra {key!r} collides with the {owner_by_key[key]} slice")

    ctx: dict = {"user": user, "nav_items": sorted(host.nav_items, key=lambda i: i.order)}
    # Registration refuses exactly these keys.
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
