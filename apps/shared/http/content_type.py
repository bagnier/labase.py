"""Which face a request wants: JSON, an HTMX fragment or a full page
(AGENTS: every business endpoint has two faces).
"""

from fastapi import Request


def wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def is_history_restore(request: Request) -> bool:
    return request.headers.get("HX-History-Restore-Request") == "true"


def wants_full_page(request: Request) -> bool:
    """A page extending base.html, which needs the fullpage slices. Includes htmx's history
    restore: it sends ``HX-Request`` but replaces the whole body."""
    if wants_json(request):
        return False
    return not is_htmx(request) or is_history_restore(request)
