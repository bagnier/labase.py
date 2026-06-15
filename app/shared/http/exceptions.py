import structlog
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.shared.http import wants_html, wants_json

log = structlog.get_logger("labase.app")


async def handle_rate_limit(_request: Request, exc: Exception) -> Response:
    headers = {}
    limit = getattr(exc, "limit", None)
    if limit is not None:
        item = getattr(limit, "limit", None)
        if item is not None:
            granularity = getattr(item.GRANULARITY, "seconds", None)
            if granularity is not None:
                headers["Retry-After"] = str(int(granularity * (item.multiples or 1)))
    return JSONResponse({"detail": "Too many requests"}, status_code=429, headers=headers)


async def handle_unhandled_error(request: Request, exc: Exception) -> Response:
    log.exception(
        "request.unhandled_error",
        method=request.method,
        path=request.url.path,
    )
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


async def handle_http_error(request: Request, exc: HTTPException) -> Response:
    if exc.status_code == 401:
        if request.headers.get("HX-Request"):
            r = Response(status_code=200)
            r.headers["HX-Redirect"] = "/auth/login"
            return r
        if wants_html(request):
            return RedirectResponse(url="/auth/login", status_code=302)
    if wants_json(request):
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=dict(exc.headers or {})
        )
    return HTMLResponse(str(exc.detail), status_code=exc.status_code)
