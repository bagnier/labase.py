"""Every session delivered emits a ``SignedIn`` (AGENTS: signing in is one fact), found by the
session cookies written, not by the helper's name. The exceptions are listed below.
"""

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"

_SESSION_COOKIES = {"access_token", "refresh_token"}
_COOKIE_WRITERS = {"set_cookie", "_set_ephemeral_cookie"}

# Deliveries without ``SignedIn``, with what they record: a refresh renews a session; stopping an
# impersonation restores the admin's; confirming an authenticator raises the session to aal2;
# starting an impersonation records the disguise.
_DELIVERIES_THAT_ARE_NOT_SIGN_INS = {
    "apps/auth/infra/router.py::impersonate_endpoint": ["ImpersonationStarted"],
    "apps/auth/infra/router.py::stop_impersonation_endpoint": ["ImpersonationStopped"],
    "apps/auth/infra/security.py::get_current_user": [],
    "apps/profile/infra/router.py::twofa_verify": ["TwoFactorEnabled"],
}


def _called_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _delivers_a_session(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node)
        if name == "set_auth_cookies":
            return True
        values = list(node.args) + [keyword.value for keyword in node.keywords]
        if name in _COOKIE_WRITERS and any(
            isinstance(value, ast.Constant) and value.value in _SESSION_COOKIES for value in values
        ):
            return True
    return False


def _events_emitted(fn: ast.AST) -> set[str]:
    """The event classes built inside an ``emit`` call."""
    emitted = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and _called_name(node) == "emit":
            for argument in node.args:
                emitted |= {
                    _called_name(inner)
                    for inner in ast.walk(argument)
                    if isinstance(inner, ast.Call) and _called_name(inner)[:1].isupper()
                }
    return emitted


def _functions_delivering_a_session() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(_APPS.rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        relative = str(path.relative_to(_ROOT))
        for fn in ast.walk(ast.parse(path.read_text())):
            if not isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            if fn.name in {"set_auth_cookies", "_set_ephemeral_cookie"}:
                continue
            if _delivers_a_session(fn):
                site = f"{relative}::{fn.name}"
                found[site] = found.get(site, set()) | _events_emitted(fn)
    return found


def test_every_delivered_session_is_recorded_as_a_sign_in():
    unrecorded = {
        site: sorted(events)
        for site, events in _functions_delivering_a_session().items()
        if "SignedIn" not in events
    }

    assert unrecorded == _DELIVERIES_THAT_ARE_NOT_SIGN_INS


def test_the_scan_actually_finds_the_delivery_points():
    """Guards the guard: a broken glob would find nothing."""
    assert len(_functions_delivering_a_session()) >= 6
