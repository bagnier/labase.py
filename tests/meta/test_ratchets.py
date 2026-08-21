"""Rules the README states as absolutes, held as the enumerated list of what is left.

Some of the base's conventions are already true everywhere and need a guard so they stay that way;
others are true almost everywhere, and the README states them anyway. Both are held the same way
here — the sites are enumerated and frozen — because the two only differ by today's number.

A frozen list is not a suppression. A suppression makes a rule stop applying to a site; a freeze
makes the site *visible*, in one place, next to the reason it is there. The tell is direction:
nothing here may grow without an edit to this file, and every edit is a decision someone made on
purpose.

``tests/meta/claims.py`` says which of these hold a README claim outright and which only measure
the distance left — a claim whose ratchet is not yet at zero stays waived, and names its ratchet.
"""

import ast
import re
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"

# The clock's own module, and the six test-side stamps that record *when the test asked*, which is
# a fact about the run and not about the domain — pinning them to the domain clock would make a
# mail-arrival window compare a real timestamp with a frozen one.
_MAY_READ_THE_WALL_CLOCK = ("apps/shared/clock.py", "/tests/")

# The logs subsystem computes the name it writes (the dependency verdict picks `…_failed` or
# `…_unreachable`, the chain re-emits whatever a library named its record). Everywhere else the
# name is a literal, which is what makes it greppable and what the Timeline's `app` axis reads.
_NAMES_ITS_LINES_AT_RUNTIME = "apps/shared/logs/"

# Reads defending against a `None` a writer really can produce: GoTrue's `app_metadata`, a JSONB
# payload column, Starlette's optional headers. Each is an external shape, not slack in one of our
# own annotations — which is the distinction the README's rule turns on. A twelfth is a decision.
_DEFENSIVE_READS = {
    "apps/auth/domain/service.py": 1,
    "apps/auth/infra/accounts_router.py": 1,
    "apps/auth/infra/user_repository.py": 1,
    "apps/console/infra/router.py": 1,
    "apps/issues/contract/queries.py": 1,
    "apps/shared/charts.py": 1,
    "apps/shared/events/repository.py": 2,
    "apps/shared/http/exceptions.py": 1,
    "apps/shared/queue.py": 1,
    "apps/timeline/infra/repository.py": 1,
}

# Every navigation the browser mixins still make by URL, and why each one is an *arrival* rather
# than a deep link. The rule the list applies: a person reaches a page by following a link or
# submitting a form, except when they arrive from outside the app entirely — the front door, a
# mailed link, an invitation token, an address typed by someone who is not signed in, a machine
# endpoint, a download. Everything else goes through the sidebar, a card or a button, like a human.
#
# A `then` may never navigate at all, whatever the reason: an assertion that fetches its own page
# asserts about a page nobody reached, and keeps passing after the app's own way there breaks.
# ``test_no_assertion_step_reaches_a_page_by_url`` holds that half; this list holds the other.
_ARRIVES_FROM_OUTSIDE = {
    # ── the front door: the sign-in and registration pages ──────────────────────────────────────
    "auth.start_to_sign_in": "a visitor sets out to sign in",
    "auth.start_to_register": "a visitor sets out to register",
    "auth.sign_in": "the sign-in page — twice, since an already-signed-in context is dropped first",
    "auth.register": "the registration page",
    "auth.ensure_registered": "the registration page, for a user a scenario needs to exist",
    "auth.start_oauth": "the sign-in page, to click the provider button on it",
    "auth.request_password_reset": 'the sign-in page, to follow its "Forgot password?" link',
    "auth.sign_in_with_passkey": "the sign-in page, to run the WebAuthn ceremony from it",
    "console.sign_in_as_admin": "the sign-in page, on the admin's own context",
    "console._login": "the sign-in page, to re-issue a token carrying a fresh claim",
    # ── a link someone was sent ─────────────────────────────────────────────────────────────────
    "auth.reset_password_via_email": "the recovery link, read from the mail catcher",
    "auth.confirm_address_via_link": "the confirmation link, read from the mail catcher",
    "profile.confirm_email_change": "the email-change link, read from the mail catcher",
    "organizations._open_invitation_page": "an invitation token, as its recipient received it",
    "organizations._accept_invitation_as": "an invitation token, as its recipient received it",
    "organizations._follow_accept_to_registration": "an invitation token, by someone with no "
    "account yet",
    # ── an address typed by someone the app does not know ───────────────────────────────────────
    "auth.visit": "the address a scenario says is typed",
    "profile.visit_profile_unauthenticated": "a protected address, with no session",
    "console.visit_console_unauthenticated": "a protected address, with no session",
    "console.try_open_console": "a protected address, by a user who is not an admin",
    "organizations.visit_org_dashboard_unauthenticated": "a protected address, with no session",
    "pages.visitor_open": "a public page's address, by an anonymous visitor",
    "pages.visitor_open_list": "an org's public listing, by an anonymous visitor",
    "pages.visitor_view_public_page": "the featured org's public page, by an anonymous visitor",
    # ── what a browser fetches rather than renders ──────────────────────────────────────────────
    "files.download_file": "the download URL the file row carries",
    "files._goto_and_capture_download": "a share token's download URL",
    "metrics.fetch_metrics_exposition": "the Prometheus endpoint, which no page links to",
}

# Requests the driver fires itself instead of clicking. Five of the six are the base's own answer
# to "hiding the control is not proof": the affordance is absent for this actor, so the request it
# would have sent is fired from their own authenticated context and the server has to be the one
# refusing. The sixth is the smell the README warns about, written down rather than left implicit.
_ASKS_THE_SERVER_DIRECTLY = {
    "organizations._probe_blocked": "the shared probe: the hidden control's own request, so a "
    "refusal is the server's and not the template's",
    "organizations.try_create_org": "the create request, so the owned-org limit is enforced by "
    "the server",
    "pages.try_publish_to_members": "the visibility request a member has no control for",
    "console.try_set_console_setting": "the settings request a non-admin has no control for",
    "console.assert_refused_console": "the console request the missing button would have sent",
    "todo.move_todo_above": "the reorder PUT, fired by hand: this one stands in for an "
    "interaction the driver never managed to drive — SortableJS's drop-above — where its "
    "neighbour move_todo_to_end really drags. The one site here that is a smell",
}

# The driver substrate's own navigations, outside any mixin: the entry point each scenario starts
# from, and the isolation tests that assert two contexts really are two.
_SUBSTRATE_DEEP_LINKS = {
    "tests/e2e/drivers/browser_base.py": 2,
    "tests/e2e/drivers/test_browser_isolation.py": 2,
}

_STEP_TYPES = {"given", "when", "then"}
_LEVELS = {"debug", "info", "warning", "error", "exception"}
_DOTTED_SNAKE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*(\.[a-z0-9]+(_[a-z0-9]+)*)*$")


def _python_files(*roots: Path):
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if not path.is_relative_to(Path(__file__).parent):
                yield path, str(path.relative_to(_ROOT))


def _sites(pattern: str, *roots: Path) -> dict[str, int]:
    """How many times ``pattern`` occurs, per file, over ``roots`` — the shape a ratchet freezes."""
    counts = {}
    for path, relative in _python_files(*roots):
        found = len(re.findall(pattern, path.read_text()))
        if found:
            counts[relative] = found
    return counts


def _log_calls():
    """Every ``log.<level>(…)`` under ``apps/``, tests aside, with the file it sits in."""
    for path, relative in _python_files(_APPS):
        if "/tests/" in path.as_posix():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LEVELS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "log"
                and node.args
            ):
                yield relative, node


def test_time_comes_from_the_one_clock():
    """A second reading of the wall clock is how a test that pins time stops pinning anything."""
    strays = {
        f"{relative}:{node.lineno}"
        for path, relative in _python_files(_APPS)
        if not any(allowed in f"/{relative}" for allowed in _MAY_READ_THE_WALL_CLOCK)
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"now", "utcnow"}
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "datetime"
    }

    assert strays == set()


def test_no_compensating_assert_narrows_an_annotation():
    """The first of the README's three tells that an annotation is wider than the truth. At zero
    today, which is the only interesting place for it to be: one `assert x is not None` is how a
    `| None` that no writer produces survives its first reader."""
    assert _sites(r"^\s*assert .* is not None", _APPS) == {}


def test_the_defensive_reads_are_the_named_ones():
    """The second tell, and the one that cannot go to zero: some of these `None`s come from
    outside the process. Frozen per file so a new one lands here as a question — is this an
    external shape, or an annotation we could narrow?"""
    reads = {
        relative: count
        for relative, count in _sites(r"or \{\}", _APPS).items()
        if "/tests/" not in relative
    }

    assert reads == _DEFENSIVE_READS


def test_no_state_wait_is_a_sleep():
    """`networkidle` waits for the network to go quiet, `wait_for_timeout` waits for the clock —
    neither waits for the state being asserted, which is why both flake under load and pass on a
    fast laptop. Both at zero; this keeps them there."""
    assert _sites(r"networkidle|wait_for_timeout\(", _APPS, _ROOT / "tests") == {}


def test_dom_state_is_asserted_through_expect():
    """`assert locator.is_visible()` reads the DOM once, at whatever moment an HTMX swap happens
    to be in. `expect(...)` retries to the settled state."""
    assert _sites(r"assert [^#\n]*\.is_visible\(\)", _APPS, _ROOT / "tests") == {}


def _called_attributes(fn: ast.AST) -> list[str]:
    """Every ``x.name(...)`` called inside ``fn``, by attribute name."""
    return [
        node.func.attr
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]


def _mixin_methods(mixin: Path) -> tuple[dict[str, int], dict[str, set[str]]]:
    """``({method: goto calls}, {method: methods it calls})`` for one browser mixin."""
    gotos, calls = {}, {}
    for cls in ast.parse(mixin.read_text()).body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for fn in cls.body:
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                attributes = _called_attributes(fn)
                gotos[fn.name] = attributes.count("goto")
                calls[fn.name] = set(attributes)
    return gotos, calls


def _steps_reaching(steps: Path) -> dict[str, set[str]]:
    """``{driver method: the Gherkin step types whose functions call it}``."""
    reached: dict[str, set[str]] = defaultdict(set)
    if not steps.exists():
        return reached
    for fn in ast.walk(ast.parse(steps.read_text())):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        kinds = {
            decorator.func.id
            for decorator in fn.decorator_list
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name)
        } & _STEP_TYPES
        for attribute in _called_attributes(fn) if kinds else []:
            reached[attribute] |= kinds
    return reached


def _propagated(reached: dict[str, set[str]], calls: dict[str, set[str]]) -> dict[str, set[str]]:
    """A helper answers for every step type that reaches its callers — run to a fixpoint, since a
    private method is often two hops from the step that uses it."""
    for method in calls:  # a method no step names still receives what its callers were reached by
        reached.setdefault(method, set())
    settled = False
    while not settled:
        settled = True
        for method, callees in calls.items():
            for callee in callees & set(reached):
                if not reached[method] <= reached[callee]:
                    reached[callee] |= reached[method]
                    settled = False
    return reached


def _mixin_navigations() -> dict[str, tuple[set[str], int]]:
    """``{app.method: (step types that reach it, goto calls)}``, over every browser mixin."""
    found = {}
    for mixin in sorted(_APPS.glob("*/tests/e2e/driver_mixin_browser.py")):
        app = mixin.relative_to(_APPS).parts[0]
        gotos, calls = _mixin_methods(mixin)
        reached = _propagated(_steps_reaching(mixin.parent / "steps.py"), calls)
        found |= {f"{app}.{name}": (reached[name], count) for name, count in gotos.items() if count}
    return found


def test_no_assertion_step_reaches_a_page_by_url():
    """The sharpest half of "the browser driver navigates like a human": a `then` that navigates
    is not asserting about the page the scenario produced, it is asserting about a page it fetched
    itself — and it keeps passing after the app's own way there breaks."""
    under_assertion = {
        method for method, (kinds, _) in _mixin_navigations().items() if "then" in kinds
    }

    assert under_assertion == set()


def test_every_deep_link_is_an_arrival_from_outside():
    """The other half: what is left may only be someone coming in from outside the app. A new
    name here is a claim that a person really arrives at that URL — the reason is written next to
    it, and nothing else navigates by URL at all."""
    navigating = set(_mixin_navigations())

    assert navigating == set(_ARRIVES_FROM_OUTSIDE)


def _fires_its_own_request(fn: ast.AST) -> bool:
    """Does this method send a request rather than click? Either through Playwright's own
    ``fetch``, or through a ``fetch(`` written into a script it evaluates in the page."""
    return any(
        (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "fetch"
        )
        or (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "fetch(" in node.value
        )
        for node in ast.walk(fn)
    )


def test_every_request_the_driver_fires_itself_is_named():
    """The other half of the README's sentence: ``fetch()`` is a smell too. Firing a request the
    UI would not let this actor send is how the base proves the *server* refuses — but each site
    has to say so, and the one that only stands in for an interaction says that instead."""
    firing = set()
    for mixin in sorted(_APPS.glob("*/tests/e2e/driver_mixin_browser.py")):
        app = mixin.relative_to(_APPS).parts[0]
        for cls in ast.parse(mixin.read_text()).body:
            if not isinstance(cls, ast.ClassDef):
                continue
            firing |= {
                f"{app}.{fn.name}"
                for fn in cls.body
                if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
                and _fires_its_own_request(fn)
            }

    assert firing == set(_ASKS_THE_SERVER_DIRECTLY)


def test_the_driver_substrate_navigates_only_where_a_scenario_starts():
    """Outside the mixins there is no step to attribute a navigation to — so these are frozen by
    file, and there are four of them."""
    assert _sites(r"\.goto\(", _ROOT / "tests") == _SUBSTRATE_DEEP_LINKS


def test_every_log_line_is_named_by_a_dotted_snake_case_literal():
    """The name is the Timeline's `app` axis and the thing an operator greps. A computed name is
    invisible to both — and to the AST walks that hold the rest of the log vocabulary."""
    strays = {
        f"{relative}:{node.lineno}"
        for relative, node in _log_calls()
        if not relative.startswith(_NAMES_ITS_LINES_AT_RUNTIME)
        and not (
            isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and _DOTTED_SNAKE.match(node.args[0].value)
        )
    }

    assert strays == set()


def test_nothing_reruns_a_failing_test():
    """ "Everything else is strict, zero rerun" — kept true the cheap way: the plugin that could
    rerun anything is not installed, so no suite can opt in by accident."""
    pyproject = (_ROOT / "pyproject.toml").read_text()

    assert ("pytest-rerunfailures" in pyproject, "--reruns" in pyproject) == (False, False)
