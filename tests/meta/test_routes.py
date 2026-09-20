"""The mounted route table, read as the app actually assembled it.

Everything else in this package reads source; this reads the FastAPI application that
``apps/main.py`` built — the only place where the composition root's ordering, every app's
prefixes and the reserved-slug registry meet. Two questions are asked of it: can a fixed route be
shadowed by an org handle, and does the schema describe both faces of a page.

The second one is a measurement, not a proof. OpenAPI records what a route *declares*, and a
handler that negotiates at runtime without declaring an HTML response looks single-faced here
while serving both. That is exactly what makes the number worth freezing: the generated client in
``client/`` is built from this schema, so a face the schema does not mention is a face no external
consumer can reach — which is the half of "two faces" that has a mechanical meaning.
"""

import re

from starlette.routing import Match

import apps.main
from apps.shared.integration import slugs

# The routes that answer one audience, split by which one — because "one face" says nothing about
# which face is missing, and the two lists fail for opposite reasons.

# JSON only: nothing here is a document. A redirect (the OAuth round-trip, the mailed
# confirmations, a permalink resolver), bytes (an avatar, a download, a share link), a machine
# surface (the probes, `/metrics`, the dashboard's own `.json` fetch), or a JSON list with no page
# of its own. `/{org_handle}/api-keys` does branch on the request, but answers HTML with a redirect
# to the settings page — a destination, not a document.
_JSON_ONLY_GETS = {
    "/auth/callback",
    "/auth/confirm",
    "/auth/confirm-email",
    "/auth/oauth/{provider}",
    "/console/timeline/export",
    "/files/share/{token}",
    "/health/live",
    "/health/ready",
    "/metrics",
    "/organizations",
    "/profile/avatar/{user_id}",
    "/{org_handle}/api-keys",
    "/{org_handle}/dashboard/overviews.json",
    "/{org_handle}/files/{file_id}/download",
    "/{org_handle}/invitations",
    "/{org_handle}/pages/by-id/{page_id}",
}

# HTML only: pages with no JSON caller. The unauthenticated forms (sign in, register, the two
# password flows), the editor forms, and the landing page — a form has no JSON meaning, and the
# data behind each editor is its own route, which does have both faces. The dashboard and the
# settings page are composed documents on the same argument: their data is its own routes
# (`overviews.json`, the activity feed, `/members`), each of which answers JSON.
_HTML_ONLY_GETS = {
    "/",
    "/auth/forgot-password",
    "/auth/login",
    "/auth/register",
    "/auth/reset-password",
    "/{org_handle}/calendar/new",
    "/{org_handle}/calendar/{event_id}/edit",
    "/{org_handle}/dashboard",
    "/{org_handle}/pages/new/edit",
    "/{org_handle}/pages/{slug}/edit",
    "/{org_handle}/settings",
}


def _paths() -> dict[str, dict]:
    return apps.main.app.openapi()["paths"]


def _fixed_top_level_segments() -> set[str]:
    """The first segment of every route that starts with a literal — the segments an org handle
    would have to be forbidden from taking."""
    return {
        segment
        for path in _paths()
        if (segment := path.split("/")[1]) and not segment.startswith("{")
    }


def _declared_content(operation: dict) -> set[str]:
    """The media types the *success* response describes.

    Only the 2xx entry counts. FastAPI adds a `422` carrying `application/json` to any route with
    something to validate, so reading every status code makes almost everything look two-faced —
    the failure this walk was written with, and the reason it says `2` out loud.
    """
    return {
        media
        for code, response in (operation.get("responses") or {}).items()
        if code.startswith("2")
        for media in (response.get("content") or {})
    }


def test_no_org_handle_can_shadow_a_fixed_route():
    """What `host.reserve(...)` is for, checked against the routes actually mounted rather than
    against the list someone remembered to write. A fixed segment nobody reserved is a handle
    someone can register, and then one of the two is unreachable for good."""
    unclaimed = {
        segment for segment in _fixed_top_level_segments() if not slugs.is_reserved(segment)
    }

    assert unclaimed == set()


def test_every_fixed_route_wins_its_first_match():
    """Registration order is the whole mechanism behind "catch-alls sort last", so this walks it
    the way Starlette will: for every fixed route, the first mounted route that matches must be
    that route itself — not `/{slug}` or `/{org_handle}` arriving too early in the table. The
    reserved-slug test above guards handles; this one guards the ordering."""
    swallowed = set()
    for path, operations in _paths().items():
        if path.split("/")[1].startswith("{"):
            continue
        concrete = re.sub(r"\{[^}]+\}", "probe", path)
        for method in operations:
            scope = {
                "type": "http",
                "method": method.upper(),
                "path": concrete,
                "root_path": "",
                "headers": [],
            }
            first_full = next(
                (
                    route
                    for route in apps.main.app.router.routes
                    if route.matches(scope)[0] is Match.FULL
                ),
                None,
            )
            if first_full is None or path not in _served_paths(first_full):
                swallowed.add(f"{method.upper()} {path} → {_served_paths(first_full)}")

    assert swallowed == set()


def _served_paths(route) -> set[str]:
    """The declared paths behind one top-level router entry. FastAPI defers `include_router`
    into a lazy entry carrying the included router and its prefix — reading it is what lets the
    walk say *which* app's routes the first match belongs to."""
    if route is None:
        return set()
    context = getattr(route, "include_context", None)
    if context is None:
        return {getattr(route, "path", "")}
    return {context.prefix + str(inner.path) for inner in context.included_router.routes}


def test_the_schema_describes_both_faces_of_every_page_but_the_named_ones():
    """ "Because every business endpoint also speaks JSON, the OpenAPI schema is a full description
    of the app" — and `client/` is generated from exactly this. Every GET route that is a document
    describes both faces; the two sets below are the routes that are not one, each named."""
    by_face = {"application/json": set(), "text/html": set()}
    for path, operations in _paths().items():
        for method, operation in operations.items():
            if method.upper() != "GET":
                continue
            declared = _declared_content(operation)
            if len(declared) == 1:
                by_face[next(iter(declared))].add(path)

    assert (by_face["application/json"], by_face["text/html"]) == (
        _JSON_ONLY_GETS,
        _HTML_ONLY_GETS,
    )
