"""The middleware stack, exercised on the app the composition root actually assembled.

The pieces here are unit-tested one class at a time under ``apps/shared/tests``; what no unit
test can say is that ``apps/main.py`` still mounts them, in an order that works. So these drive
the assembled app itself, the way a browser would — and they pick requests the CSRF middleware
refuses before routing, so no database is touched.
"""

import httpx
import pytest
from structlog.testing import capture_logs

import apps.main
from apps.shared.contract import integration as shared_integration
from apps.shared.integration.host import Host


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


@pytest.mark.asyncio
async def test_a_served_request_leaves_exactly_one_finished_line():
    """ "Every served request leaves one `request.finished` line" — end to end, with the sink
    captured: one exchange, one line, carrying the outcome. A 403 we refused on purpose is the
    `warning` tier."""
    transport = httpx.ASGITransport(app=apps.main.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with capture_logs() as logs:
            await client.post("/auth/login", headers={"sec-fetch-site": "cross-site"})

    finished = [
        (line["status"], line["log_level"]) for line in logs if line["event"] == "request.finished"
    ]
    assert finished == [(403, "warning")]


@pytest.mark.asyncio
async def test_a_refused_preflight_still_leaves_its_finished_line():
    """ "Every served request leaves one `request.finished` line" — held against a CORS preflight
    too: with no origin configured (the default) it is CORSMiddleware itself that answers, so it
    must sit *inside* RequestLogger rather than wrap it."""
    transport = httpx.ASGITransport(app=apps.main.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with capture_logs() as logs:
            await client.options(
                "/auth/login",
                headers={
                    "Origin": "https://evil.example",
                    "Access-Control-Request-Method": "POST",
                },
            )

    finished = [line["status"] for line in logs if line["event"] == "request.finished"]
    assert finished == [400]


@pytest.mark.asyncio
async def test_a_request_whose_handler_raised_still_leaves_its_finished_line():
    """The other half of the sentence — "including one whose handler raised": the exchange ends
    as a 500 and its one line carries `error`. Driven on a fresh host wearing the foundation's
    own mount, since the assembled app deliberately has no route that raises."""
    host = Host()
    shared_integration.mount(host)

    @host.app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    transport = httpx.ASGITransport(app=host.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with capture_logs() as logs:
            response = await client.get("/boom")

    finished = [
        (line["status"], line["log_level"]) for line in logs if line["event"] == "request.finished"
    ]
    assert (response.status_code, finished) == (500, [(500, "error")])
