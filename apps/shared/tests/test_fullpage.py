"""fullpage_context — page-slice assembly; a route's page extras must not silently clobber
a provider's namespaced slice (see the *Page composition* principle: each slice is owned by
the app that provides it)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.integration.fullpage import FullpageQuery, fullpage_context
from apps.shared.integration.host import FullpageProvider, host


@pytest.mark.asyncio
async def test_a_route_extra_named_like_a_provider_key_is_refused(
    db_session: AsyncSession, monkeypatch
):
    async def provide_profile(query: FullpageQuery) -> dict:
        return {"handle": "real-handle"}

    monkeypatch.setattr(host, "fullpage_providers", [FullpageProvider("profile", provide_profile)])

    with pytest.raises(ValueError, match="collides") as err:
        await fullpage_context(db_session, None, profile_handle="forged")

    assert str(err.value) == "page extra 'profile_handle' collides with the profile slice"


@pytest.mark.asyncio
async def test_a_route_extra_with_no_matching_provider_key_lands_in_the_context(
    db_session: AsyncSession, monkeypatch
):
    async def provide_profile(query: FullpageQuery) -> dict:
        return {"handle": "real-handle"}

    monkeypatch.setattr(host, "fullpage_providers", [FullpageProvider("profile", provide_profile)])

    ctx = await fullpage_context(db_session, None, org_handle="acme")

    assert (ctx["org_handle"], ctx["profile_handle"]) == ("acme", "real-handle")
