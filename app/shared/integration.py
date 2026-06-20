from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from app.integration import Host
from app.shared.config import get_settings
from app.shared.http.exceptions import handle_http_error, handle_rate_limit, handle_unhandled_error
from app.shared.http.limiter import limiter
from app.shared.http.security import cors_config, security_headers
from app.shared.observability.logging import setup_logging
from app.shared.observability.request import RequestLogger

_STATIC_DIR = Path(__file__).parents[2] / "static"


def register(app: FastAPI, host: Host) -> None:
    setup_logging()
    settings = get_settings()

    app.state.limiter = limiter

    app.exception_handler(RateLimitExceeded)(handle_rate_limit)
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
