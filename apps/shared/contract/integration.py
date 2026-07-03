from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from apps.shared.config import get_technical_settings
from apps.shared.host import Host
from apps.shared.http.exceptions import (
    handle_http_error,
    handle_rate_limit,
    handle_stale_data,
    handle_unhandled_error,
)
from apps.shared.http.limiter import limiter
from apps.shared.http.security import cors_config, security_headers
from apps.shared.observability.logging import setup_logging
from apps.shared.observability.request import RequestLogger

_STATIC_DIR = Path(__file__).parents[3] / "static"


def mount(host: Host) -> None:
    setup_logging()
    settings = get_technical_settings()
    app = host.app

    app.state.limiter = limiter

    app.exception_handler(RateLimitExceeded)(handle_rate_limit)
    app.exception_handler(StaleDataError)(handle_stale_data)
    app.exception_handler(500)(handle_unhandled_error)
    app.exception_handler(HTTPException)(handle_http_error)
    app.exception_handler(StarletteHTTPException)(handle_http_error)

    app.middleware("http")(security_headers)
    app.add_middleware(RequestLogger)
    app.add_middleware(CORSMiddleware, **cors_config(settings.cors_origins))

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    host.reserve("static", "api")  # infra-owned slugs (StaticFiles mount + reserved API namespace)
