"""Content negotiation — one handler answers JSON, HTMX fragment, or full page.

The request's ``Accept`` and ``HX-Request`` headers pick the face; these predicates
let a single handler branch without a separate frontend (AGENTS: every business
endpoint has two faces). The request side needs no predicate: a form is JSON at the door
(:mod:`apps.shared.http.form`), so a handler declares its body once, as a Pydantic model.
"""

from fastapi import Request


def wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def is_htmx(request: Request) -> bool:
    """True when the request comes from HTMX — the single source of truth for the header."""
    return request.headers.get("HX-Request") == "true"


def wants_full_page(request: Request) -> bool:
    """True when the response is a standalone HTML page (not JSON, not an HTMX swap).

    Only full pages extend base.html and therefore need the fullpage slices.
    """
    if wants_json(request):
        return False
    return not is_htmx(request)
