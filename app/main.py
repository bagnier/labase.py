from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from app.auth.contract import integration as auth
from app.console.contract import integration as console
from app.files.contract import integration as files
from app.health.contract import integration as health
from app.integration import host
from app.learning.contract import integration as learning
from app.organizations.contract import integration as organizations
from app.profile.contract import integration as profile
from app.public.contract import integration as public
from app.shared.config import get_settings
from app.shared.http.exceptions import handle_http_error, handle_rate_limit, handle_unhandled_error
from app.shared.http.limiter import limiter
from app.shared.http.security import cors_config, security_headers
from app.shared.observability.logging import setup_logging
from app.shared.observability.request import RequestLogger
from app.todo.contract import integration as todo

setup_logging()

BASE_DIR = Path(__file__).parent
_settings = get_settings()

app = FastAPI(title="labase")
app.state.limiter = limiter

app.exception_handler(RateLimitExceeded)(handle_rate_limit)
app.exception_handler(500)(handle_unhandled_error)
app.exception_handler(HTTPException)(handle_http_error)
app.exception_handler(StarletteHTTPException)(handle_http_error)

app.middleware("http")(security_headers)
app.add_middleware(RequestLogger)
app.add_middleware(CORSMiddleware, **cors_config(_settings.cors_origins))

app.mount("/static", StaticFiles(directory=str(BASE_DIR.parent / "static")), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


# Composition root: each context declares everything from its contract/integration.register —
# mounts its routers, subscribes to events, answers collaboration queries, claims its URL slugs.
# Listed in dependency order (auth → org → org-scoped apps → cross-cutting → infra); routing
# precedence needs no special ordering since reserved slugs keep org handles off these paths.
# Event subscriptions are wired unconditionally; seeding is gated at its emission site
# (app.registration) so BDD scenarios under the test schema start from an empty org.
for _ctx in (auth, organizations, files, todo, learning, profile, console, public, health):
    _ctx.register(app, host)

host.reserve("static", "api")  # infra-owned slugs (StaticFiles mount + reserved API namespace)
