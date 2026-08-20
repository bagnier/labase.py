import structlog
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response

from apps.shared.http import is_htmx, wants_json
from apps.shared.http.templates import templates
from apps.shared.observability.request import note_rejection

log = structlog.get_logger(__name__)

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
    headers = {"Retry-After": str(getattr(exc, "retry_after", 60))}
    return JSONResponse({"detail": "Too many requests"}, status_code=429, headers=headers)


async def handle_stale_data(request: Request, _exc: Exception) -> Response:
    detail = "This was changed by someone else. Please retry."
    note_rejection(detail)
    if wants_json(request):
        return JSONResponse({"detail": detail}, status_code=409)
    return _html_error(request, 409, detail)


def _echo_request_id(response: Response) -> Response:
    """Put the request id on a response the request middleware never got to see.

    ``RequestLogger`` stamps every response it hands back, but a 500 is built *above* it, by
    Starlette's own error middleware, on the way out of an exception that flew past. Without this
    the one page where the id matters most — the error page a user is looking at while an admin
    asks "when was this?" — is the only one that does not carry it. Read from the contextvar the
    middleware bound, which this handler still sees: it runs on the same task, not a child of it.
    """
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    if request_id is not None:
        response.headers["X-Request-ID"] = str(request_id)
    return response


async def handle_unhandled_error(request: Request, exc: Exception) -> Response:
    # This line *is* the capture seam — the processor folds it into an issue, so nothing else
    # has to. ``exc`` is passed rather than left to ``sys.exc_info()``: the seam then holds
    # wherever the handler is called from, not only from inside a live ``except`` block.
    log.exception(
        "request.unhandled_error",
        exc_info=exc,
        method=request.method,
        path=request.url.path,
    )
    if wants_json(request):
        return _echo_request_id(JSONResponse({"detail": "Internal server error"}, status_code=500))
    return _echo_request_id(_html_error(request, 500, "An unexpected error occurred."))


async def handle_http_error(request: Request, exc: HTTPException) -> Response:
    # Every rejected request lands here, and none of them writes a line: ``request.finished``
    # already reports this exchange once, with its status and now with this reason. A second line
    # said the same thing twice — and, unlike the first, traced the asset 404s the browser fetches
    # on its own. Security-relevant rejections still emit their typed BusinessEvent from their own
    # call site; this is only the shape of the answer.
    note_rejection(str(exc.detail))
    if exc.status_code == 401:
        if is_htmx(request):
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
