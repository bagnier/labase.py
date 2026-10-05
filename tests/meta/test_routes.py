"""The route table ``apps/main.py`` assembled: no fixed route can be shadowed by an org handle,
and the schema, from which ``client/`` is generated, declares each route's faces.
"""

import re
from collections import Counter

from starlette.routing import Match

import apps.main
from apps.metrics.domain.accumulator import KNOWN_METHODS
from apps.shared.integration import slugs

# Routes with one face, split by which.

# JSON only: mutations whose HTML answer is a redirect, machine surfaces (probes, `.json` fetches,
# WebAuthn, the nav reorder), lists without a page, mutations a page's script calls.
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

# HTML only: forms, the landing page, and composed pages whose data has JSON routes of its own.
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
    """First segments of routes starting with a literal."""
    return {
        segment
        for path in _paths()
        if (segment := path.split("/")[1]) and not segment.startswith("{")
    }


def _declared_content(operation: dict) -> set[str]:
    """Faces of the 2xx responses only (FastAPI adds a JSON 422 everywhere); a 204 counts as
    JSON."""
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
    """Each fixed first segment of the mounted routes is reserved."""
    unclaimed = {
        segment for segment in _fixed_top_level_segments() if not slugs.is_reserved(segment)
    }

    assert unclaimed == set()


def test_every_fixed_route_wins_its_first_match():
    """For each fixed route, the first match in registration order is itself."""
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
    """Paths behind a lazy `include_router` entry, to name the app of a match."""
    if route is None:
        return set()
    context = getattr(route, "include_context", None)
    if context is None:
        return {getattr(route, "path", "")}
    return {context.prefix + str(inner.path) for inner in context.included_router.routes}


def test_the_schema_describes_both_faces_of_every_page_but_the_named_ones():
    """Every route but those listed declares both faces."""
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


# Mutations without a body: the path names the resource. Not `DELETE /profile`: it reads a
# password.
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

# No face: redirects, bytes (an avatar), text (Prometheus, the timeline exports).
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
    """(AGENTS: a form is JSON at the door) Every mutation with a body declares it."""
    undeclared = {
        f"{method.upper()} {path}"
        for path, operations in _paths().items()
        for method, operation in operations.items()
        if method.upper() != "GET" and "requestBody" not in operation
    }

    assert undeclared == _BODYLESS_MUTATIONS


def test_every_declared_method_is_one_the_load_metrics_know():
    """`KNOWN_METHODS` (apps/metrics) holds every mounted verb, or real traffic would count as
    ``OTHER_METHOD``."""
    declared = {method.upper() for operations in _paths().values() for method in operations}

    assert declared <= KNOWN_METHODS


def test_every_operation_has_its_own_id():
    """`client/` has one module per `operationId`; FastAPI gives a multi-method route one id for
    all its operations."""
    ids = [
        operation["operationId"]
        for operations in _paths().values()
        for operation in operations.values()
    ]
    duplicates = {operation_id for operation_id, count in Counter(ids).items() if count > 1}

    assert duplicates == set()


def test_every_json_face_declares_its_schema():
    """A JSON face declares its model, which `tests/e2e/drivers/conformance.py` checks."""
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
