"""The middleware stack as ``apps/main.py`` assembles it, with requests refused before routing,
so no database is touched."""

import httpx
import pytest
from structlog.testing import capture_logs

import apps.main
from apps.shared.contract import integration as shared_integration
from apps.shared.integration.host import Host


@pytest.mark.asyncio
async def test_a_cross_site_mutation_is_rejected_by_the_assembled_app():
    transport = httpx.ASGITransport(app=apps.main.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/auth/login", headers={"sec-fetch-site": "cross-site"})

    assert (response.status_code, response.json()) == (
        403,
        {"detail": "Cross-site request rejected"},
    )


@pytest.mark.asyncio
async def test_a_served_request_leaves_exactly_one_finished_line():
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
    """CORSMiddleware answers it, so it must sit inside RequestLogger."""
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
    """On a fresh host with the foundation mount: the real app has no raising route."""
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
