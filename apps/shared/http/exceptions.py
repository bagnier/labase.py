import structlog
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response

from apps.shared.http import wants_json
from apps.shared.http.templates import templates

log = structlog.get_logger("labase.app")

_ERROR_TEMPLATES: dict[int, str] = {
    403: "errors/403.html",
    404: "errors/404.html",
    500: "errors/500.html",
}


def _html_error(request: Request, status_code: int, detail: str) -> Response:
    template = _ERROR_TEMPLATES.get(status_code, "errors/error.html")
    return templates.TemplateResponse(
        request,
        template,
        {"status_code": status_code, "detail": detail},
        status_code=status_code,
    )


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


async def handle_stale_data(request: Request, _exc: Exception) -> Response:
    log.warning("request.conflict", method=request.method, path=request.url.path)
    detail = "This was changed by someone else. Please retry."
    if wants_json(request):
        return JSONResponse({"detail": detail}, status_code=409)
    return _html_error(request, 409, detail)


async def handle_unhandled_error(request: Request, exc: Exception) -> Response:
    log.exception(
        "request.unhandled_error",
        method=request.method,
        path=request.url.path,
    )
    if wants_json(request):
        return JSONResponse({"detail": "Internal server error"}, status_code=500)
    return _html_error(request, 500, "An unexpected error occurred.")


async def handle_http_error(request: Request, exc: HTTPException) -> Response:
    # Every rejected request lands here — a generic, cheap trace even for routes that don't
    # call record_audit_event themselves. Security-relevant rejections get a proper audit_logs
    # row from their own call site (see apps/shared/observability/audit.py); this is the catch-all.
    log_fn = log.error if exc.status_code >= 500 else log.warning
    log_fn(
        "request.rejected",
        status_code=exc.status_code,
        method=request.method,
        path=request.url.path,
        detail=str(exc.detail),
    )
    if exc.status_code == 401:
        if request.headers.get("HX-Request"):
            r = Response(status_code=status.HTTP_204_NO_CONTENT)
            r.headers["HX-Redirect"] = "/auth/login"
            return r
        if not wants_json(request):
            next_url = str(request.url.path)
            if request.url.query:
                next_url += f"?{request.url.query}"
            return RedirectResponse(url=f"/auth/login?next={next_url}", status_code=302)
    if wants_json(request):
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=dict(exc.headers or {})
        )
    return _html_error(request, exc.status_code, str(exc.detail))
