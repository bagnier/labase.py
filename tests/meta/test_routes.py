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
from apps.metrics.domain.accumulator import KNOWN_METHODS
from apps.shared.integration import slugs

# The routes that answer one audience, split by which one — because "one face" says nothing about
# which face is missing, and the two lists fail for opposite reasons. Every method: a mutation
# that negotiates and declares one face is a mutation the generated client cannot send as JSON.

# JSON only: nothing here is a document. Every mutation whose HTML answer is a redirect to the
# page it changed (sign-in and its second factor, registration, impersonation, the account
# deletions, an accepted invitation, the org and page edits), a machine surface (the probes,
# the dashboard's own `.json` fetch, the WebAuthn ceremonies, the nav reorder PUT), a JSON list
# with no page of its own, or a JSON mutation the page reaches by script (the pages CRUD, the
# calendar writes). `/{org_handle}/api-keys` does branch on the request, but answers HTML with a
# redirect to the settings page — a destination, not a document.
_JSON_ONLY = {
    "GET /health/live",
    "GET /health/ready",
    "GET /organizations",
    "GET /{org_handle}/api-keys",
    "GET /{org_handle}/dashboard/overviews.json",
    "GET /{org_handle}/invitations",
    "PATCH /{org_handle}",
    "PATCH /{org_handle}/handle",
    "PATCH /{org_handle}/timezone",
    "DELETE /{org_handle}/members/me",
    "POST /auth/impersonate",
    "POST /auth/impersonate/stop",
    "POST /auth/mfa",
    "POST /invitations/{token}/accept",
    "POST /profile/2fa/enroll",
    "POST /auth/login",
    "POST /auth/passkeys/options",
    "POST /auth/passkeys/verify",
    "POST /auth/register",
    "POST /auth/reset-password",
    "POST /organizations",
    "DELETE /profile",
    "POST /profile/delete",
    "POST /profile/passkeys/options",
    "POST /profile/passkeys/verify",
    "POST /{org_handle}/calendar",
    "DELETE /{org_handle}/calendar/{event_id}",
    "PATCH /{org_handle}/calendar/{event_id}",
    "POST /{org_handle}/calendar/{event_id}",
    "POST /{org_handle}/pages",
    "POST /{org_handle}/pages/nav",
    "DELETE /{org_handle}/pages/nav/{slug}",
    "PUT /{org_handle}/pages/nav/{slug}/position",
    "PATCH /{org_handle}/pages/{slug}",
    "DELETE /{org_handle}/pages/{slug}",
    "POST /{org_handle}/pages/{slug}/visibility",
}

# HTML only: pages with no JSON caller. The unauthenticated forms (sign in, register, the two
# password flows, a mailed link's confirmation, the second-factor code), the editor forms, and the
# landing page — a form has no JSON meaning, and the data behind each editor is its own route,
# which does have both faces. The dashboard and the settings page are composed documents on the
# same argument: their data is its own routes (`overviews.json`, the activity feed, `/members`),
# each of which answers JSON.
_HTML_ONLY = {
    "GET /",
    "GET /auth/confirm",
    "GET /auth/confirm-email",
    "GET /auth/forgot-password",
    "GET /auth/login",
    "GET /auth/mfa",
    "GET /auth/register",
    "GET /auth/reset-password",
    "GET /{org_handle}/calendar/new",
    "GET /{org_handle}/calendar/{event_id}/edit",
    "GET /{org_handle}/dashboard",
    "GET /{org_handle}/pages/new/edit",
    "GET /{org_handle}/pages/{slug}/edit",
    "GET /{org_handle}/settings",
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
    """The two faces the *success* responses describe — bytes, text and a redirect are no face.

    Only the 2xx entries count. FastAPI adds a `422` carrying `application/json` to any route with
    something to validate, so reading every status code makes almost everything look two-faced —
    the failure this walk was written with, and the reason it says `2` out loud. A `204` carries
    no content by definition and is what a JSON caller gets from a deletion: it counts as the
    JSON face.
    """
    faces = {
        media
        for code, response in (operation.get("responses") or {}).items()
        if code.startswith("2")
        for media in (response.get("content") or {})
        if media in ("application/json", "text/html")
    }
    if "204" in (operation.get("responses") or {}):
        faces.add("application/json")
    return faces


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
    of the app" — and `client/` is generated from exactly this. Every route that serves a document,
    reads or writes, describes both faces; the two sets above are the routes that are not one,
    each named. A mutation is where the gap costs most: it negotiates at runtime, so a
    `response_class` naming one face documents the other out of the client's reach."""
    by_face = {"application/json": set(), "text/html": set(), "none": set()}
    for path, operations in _paths().items():
        for method, operation in operations.items():
            declared = _declared_content(operation)
            if len(declared) == 1:
                by_face[next(iter(declared))].add(f"{method.upper()} {path}")
            elif not declared:
                by_face["none"].add(f"{method.upper()} {path}")

    assert (by_face["application/json"], by_face["text/html"], by_face["none"]) == (
        _JSON_ONLY,
        _HTML_ONLY,
        _NO_FACE,
    )


# Mutations that carry no body: a verb on a resource the path already names — a deletion, a
# toggle, a sign-out, a ceremony's opening request, a share link minted for the file in the URL.
# Not `DELETE /profile`: deleting an account re-authenticates, so it reads a password.
_BODYLESS_MUTATIONS = {
    "DELETE /console/{app}/org-settings/{key}/{org_id}",
    "DELETE /{org_handle}/api-keys/{key_id}",
    "DELETE /{org_handle}/calendar/{event_id}",
    "DELETE /{org_handle}/files/{file_id}",
    "DELETE /{org_handle}/invitations/{invitation_id}",
    "DELETE /{org_handle}/members/me",
    "DELETE /{org_handle}/members/{user_id}",
    "DELETE /{org_handle}/pages/nav/{slug}",
    "DELETE /{org_handle}/pages/{slug}",
    "DELETE /{org_handle}/todos/{todo_id}",
    "POST /auth/impersonate/stop",
    "POST /auth/logout",
    "POST /auth/passkeys/options",
    "POST /console/accounts/{user_id}/delete",
    "POST /console/accounts/{user_id}/disable",
    "POST /console/accounts/{user_id}/enable",
    "POST /invitations/{token}/accept",
    "POST /profile/2fa/enroll",
    "POST /profile/passkeys/options",
    "POST /profile/passkeys/{passkey_id}/delete",
    "POST /{org_handle}/files/{file_id}/share",
}

# No face at all: a redirect (the OAuth round-trip, the mailed confirmations, sign-out, a
# permalink resolver, a download through a signed URL), bytes (an avatar), text (the Prometheus
# exposition, the timeline's CSV and NDJSON export). Declared as what they are, so the schema
# stops promising a JSON document nobody serves.
_NO_FACE = {
    "GET /auth/callback",
    "POST /auth/confirm",
    "POST /auth/confirm-email",
    "GET /auth/oauth/{provider}",
    "POST /auth/logout",
    "GET /console/timeline/export",
    "GET /files/share/{token}",
    "GET /metrics",
    "GET /profile/avatar/{user_id}",
    "GET /{org_handle}/files/{file_id}/download",
    "GET /{org_handle}/pages/by-id/{page_id}",
}


def test_every_mutation_declares_the_body_it_reads():
    """ "One implementation buys a documented REST API": a mutation is documented when the schema
    says what it takes. A form is JSON at the door (`apps/shared/http/form.py`), so every handler
    can declare its body as a Pydantic model and FastAPI writes the `requestBody` — a handler
    still reading the request by hand is a mutation the client cannot call."""
    undeclared = {
        f"{method.upper()} {path}"
        for path, operations in _paths().items()
        for method, operation in operations.items()
        if method.upper() != "GET" and "requestBody" not in operation
    }

    assert undeclared == _BODYLESS_MUTATIONS


def test_every_declared_method_is_one_the_load_metrics_know():
    """`KNOWN_METHODS` (apps/metrics) claims to be every verb our own routes ever declare, plus
    the two Starlette answers on their behalf — the premise that lets a made-up verb collapse
    into ``OTHER_METHOD`` without losing real traffic. Read against the mounted route table
    rather than trusted on the comment alone, so a route declaring an uncommon verb (e.g.
    `methods=["PURGE"]`) is caught here instead of silently merging into scanner noise."""
    declared = {method.upper() for operations in _paths().values() for method in operations}

    assert declared <= KNOWN_METHODS


def test_every_json_face_declares_its_schema():
    """The other half of "documented": what a JSON answer contains. `json_and_html(Model)` and
    `response_model=` name it, the API lane checks every answer against it (see
    `tests/e2e/drivers/conformance.py`), and this is what forbids the `{}` a face
    declared without its model leaves behind."""
    blank = {
        f"{method.upper()} {path} {code}"
        for path, operations in _paths().items()
        for method, operation in operations.items()
        for code, response in (operation.get("responses") or {}).items()
        if code.startswith("2")
        and "application/json" in (response.get("content") or {})
        and not response["content"]["application/json"].get("schema")
    }

    assert blank == set()
