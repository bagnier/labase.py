"""The middleware stack, exercised on the app the composition root actually assembled.

The CSRF middleware is unit-tested in ``apps/shared/tests/test_security.py``; what no unit test
can say is that ``apps/main.py`` still mounts it. So this drives the assembled app itself, the
way a browser would: the rejection below only happens if ``CsrfProtect`` sits in the stack that
serves real requests. The refusal short-circuits before routing, so no database is touched.
"""

import httpx
import pytest

import apps.main


@pytest.mark.asyncio
async def test_a_cross_site_mutation_is_rejected_by_the_assembled_app():
    """ "Cross-site mutations are rejected by a `Sec-Fetch-Site` middleware" — held against the
    mounted stack, not the class: a browser-shaped POST from another site gets the 403."""
    transport = httpx.ASGITransport(app=apps.main.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/auth/login", headers={"sec-fetch-site": "cross-site"})

    assert (response.status_code, response.json()) == (
        403,
        {"detail": "Cross-site request rejected"},
    )
