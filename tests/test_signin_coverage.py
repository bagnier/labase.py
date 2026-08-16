"""The rule: every session delivered is recorded, whatever the ceremony that produced it.

``set_auth_cookies`` is the one place a session is handed to a caller, so it is the one place where
coverage can be checked. Before this invariant existed the vocabulary had four sign-in kinds and
still missed two paths entirely — the mailed confirmation links, one of which delivers the very
first session of every account.

The two exemptions below are *re-issues*, not sign-ins: a token refresh renews the session the
caller already holds, and stopping an impersonation restores the admin's own stashed one. Adding a
third exemption is a real decision — it means a session someone can use that the trail will not
show.
"""

import ast
from pathlib import Path

_APPS = Path(__file__).resolve().parent.parent / "apps"

_REISSUES = {
    "get_current_user",  # refreshes the caller's own expiring session on an ExpiredSignatureError
    "stop_impersonation_endpoint",  # restores the admin's stashed session
}


def _functions_delivering_a_session() -> dict[str, bool]:
    """Every function that calls ``set_auth_cookies``, mapped to whether it also records a sign-in.

    Keyed by function name: the check is about *which ceremonies* deliver a session, and a name is
    what the exemption list can be written in. The helper's own definition is skipped — it takes the
    response, it does not decide anything."""
    found: dict[str, bool] = {}
    for path in _APPS.rglob("*.py"):
        if "/tests/" in path.as_posix():
            continue
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            if fn.name == "set_auth_cookies":
                continue
            called = {
                c.func.id
                for c in ast.walk(fn)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            }
            if "set_auth_cookies" not in called:
                continue
            records = "SignedIn" in called
            found[fn.name] = found.get(fn.name, False) or records
    return found


def test_every_delivered_session_is_recorded_as_a_sign_in():
    silent = {name for name, records in _functions_delivering_a_session().items() if not records}

    assert silent == _REISSUES


def test_the_scan_actually_finds_the_delivery_points():
    # Guards the guard: a broken glob would leave the assertion above comparing two empty sets
    # against an exemption list that is not empty — but say it plainly rather than by luck.
    assert len(_functions_delivering_a_session()) >= 6
