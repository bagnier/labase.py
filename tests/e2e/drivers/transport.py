import httpx

from apps.main import host
from tests.e2e.drivers.async_runner import AsyncRunner

app = host.app


class ASGISyncTransport(httpx.BaseTransport):
    def __init__(self, runner: AsyncRunner) -> None:
        self._asgi = httpx.ASGITransport(app=app)
        self._runner = runner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        async def _send() -> httpx.Response:
            resp = await self._asgi.handle_async_request(request)
            content = await resp.aread()
            return httpx.Response(
                status_code=resp.status_code,
                headers=resp.headers,
                content=content,
                request=request,
            )

        return self._runner.run(_send())
