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


def is_history_restore(request: Request) -> bool:
    """True on htmx's history restore — it also sends ``HX-Request``, but replaces the body."""
    return request.headers.get("HX-History-Restore-Request") == "true"


def wants_full_page(request: Request) -> bool:
    """True when the response is a standalone HTML page (not JSON, not an HTMX swap).

    Only full pages extend base.html and therefore need the fullpage slices. A history
    restore carries ``HX-Request`` too, but htmx swaps it into the whole body, so it needs
    the full page rather than a fragment.
    """
    if wants_json(request):
        return False
    return not is_htmx(request) or is_history_restore(request)
