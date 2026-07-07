"""Content negotiation — one handler answers JSON, HTMX fragment, or full page.

The request's ``Accept`` and ``HX-Request`` headers pick the face; these predicates
let a single handler branch without a separate frontend (README: every business
endpoint has two faces).
"""

from fastapi import Request


def _has_json_body(request: Request) -> bool:
    return "application/json" in request.headers.get("content-type", "")


async def parse_body(request: Request) -> dict:
    if _has_json_body(request):
        return await request.json()
    return dict(await request.form())


async def parse_field(request: Request, field: str) -> str:
    body = await parse_body(request)
    return str(body.get(field, ""))


def wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def wants_full_page(request: Request) -> bool:
    """True when the response is a standalone HTML page (not JSON, not an HTMX swap).

    Only full pages extend base.html and therefore need the fullpage slices.
    """
    if wants_json(request):
        return False
    return request.headers.get("HX-Request") != "true"
