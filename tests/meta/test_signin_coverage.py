"""The rule: every session delivered is recorded, whatever the ceremony that produced it.

``set_auth_cookies`` is the one place a session is handed to a caller — and the scan below is
what keeps that sentence honest: it looks for the *cookies*, not for the helper's name, so a
ceremony that writes ``access_token`` onto a response by hand is a delivery too, whether or not
it ever heard of the helper. Before this invariant existed the vocabulary had four sign-in kinds
and still missed two paths entirely — the mailed confirmation links, one of which delivers the
very first session of every account.

Recording means a ``SignedIn`` handed to ``emit`` — a constructed event nothing emits records
nothing. What may deliver without one is written out in full below: the two *re-issues* the
README names, and the impersonation pair, each recorded as the disguise it is rather than as a
sign-in. Adding an entry is a real decision — it means a session someone can use that the
journal will not show as one.
"""

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"

_SESSION_COOKIES = {"access_token", "refresh_token"}
_COOKIE_WRITERS = {"set_cookie", "_set_ephemeral_cookie"}

# Every ceremony allowed to deliver a session without recording a sign-in, with what it records
# instead. The re-issues record nothing: a token refresh renews the session the caller already
# holds, and stopping an impersonation restores the admin's own stashed one — which still says
# so on the journal. Starting one delivers the *target's* session, and the disguise is the fact.
_DELIVERIES_THAT_ARE_NOT_SIGN_INS = {
    "apps/auth/infra/router.py::impersonate_endpoint": ["ImpersonationStarted"],
    "apps/auth/infra/router.py::stop_impersonation_endpoint": ["ImpersonationStopped"],
    "apps/auth/infra/security.py::get_current_user": [],
}


def _called_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _delivers_a_session(fn: ast.AST) -> bool:
    """Does this function hand a session to the caller — through the helper, or by writing a
    session cookie itself?"""
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
    """The event classes this function constructs *inside an emit call* — a `SignedIn` built and
    never emitted records nothing."""
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
    """Every function that delivers a session, mapped to the events it emits."""
    found: dict[str, set[str]] = {}
    for path in sorted(_APPS.rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        relative = str(path.relative_to(_ROOT))
        for fn in ast.walk(ast.parse(path.read_text())):
            if not isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            # The helper takes the response it is given; it decides nothing.
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
    """Guards the guard: a broken glob would leave the assertion above comparing two empty sets
    against an exemption list that is not empty — but say it plainly rather than by luck."""
    assert len(_functions_delivering_a_session()) >= 6
