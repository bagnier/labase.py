"""``fullpage_context`` refuses a route extra named like a claimed slice. The check runs before
any provider, so an unbound ``AsyncSession`` is enough."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.integration.fullpage import fullpage_context
from apps.shared.integration.host import Host


async def _unreachable(query: object) -> dict:
    raise AssertionError("collision must be caught before a provider ever runs")


@pytest.mark.asyncio
async def test_a_route_extra_named_like_a_providers_declared_key_is_refused(monkeypatch):
    provider_host = Host()
    provider_host.register_fullpage_provider("profile", ["handle"], _unreachable)
    monkeypatch.setattr(
        "apps.shared.integration.fullpage.host.fullpage_providers",
        provider_host.fullpage_providers,
    )

    with pytest.raises(ValueError, match="collides") as err:
        await fullpage_context(AsyncSession(), None, profile_handle="forged")

    assert str(err.value) == "page extra 'profile_handle' collides with the profile slice"


@pytest.mark.asyncio
async def test_a_route_extra_named_like_the_hosts_own_nav_items_key_is_refused(monkeypatch):
    monkeypatch.setattr("apps.shared.integration.fullpage.host.fullpage_providers", [])

    with pytest.raises(ValueError, match="collides") as err:
        await fullpage_context(AsyncSession(), None, nav_items=["forged"])

    assert str(err.value) == "page extra 'nav_items' collides with the (host) slice"


@pytest.mark.asyncio
async def test_a_route_extra_with_no_matching_slice_key_lands_in_the_context(monkeypatch):
    async def provide_profile(query: object) -> dict:
        return {"handle": "real-handle"}

    provider_host = Host()
    provider_host.register_fullpage_provider("profile", ["handle"], provide_profile)
    monkeypatch.setattr(
        "apps.shared.integration.fullpage.host.fullpage_providers",
        provider_host.fullpage_providers,
    )

    ctx = await fullpage_context(AsyncSession(), None, org_handle="acme")

    assert (ctx["org_handle"], ctx["profile_handle"]) == ("acme", "real-handle")
