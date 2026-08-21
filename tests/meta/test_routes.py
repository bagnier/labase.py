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
# password flows), the editor forms, and the public surfaces — a landing page and a published page,
# read by a browser and a crawler, neither of which asks for JSON.
_HTML_ONLY_GETS = {
    "/",
    "/auth/forgot-password",
    "/auth/login",
    "/auth/register",
    "/auth/reset-password",
    "/{org_handle}/calendar/new",
    "/{org_handle}/calendar/{event_id}/edit",
    "/{org_handle}/pages/new/edit",
    "/{org_handle}/pages/{slug}",
    "/{org_handle}/pages/{slug}/edit",
    "/{slug}",
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
