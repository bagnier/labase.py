import structlog
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

log = structlog.get_logger("labase.app")


async def handle_rate_limit(_request: Request, _exc: Exception) -> Response:
    return JSONResponse({"detail": "Too many requests"}, status_code=429)


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
        if "text/html" in request.headers.get("Accept", ""):
            return RedirectResponse(url="/auth/login", status_code=302)
    return JSONResponse(
        {"detail": exc.detail}, status_code=exc.status_code, headers=dict(exc.headers or {})
    )
