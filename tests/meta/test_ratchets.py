"""Rules the README states as absolutes, held as counts that may only go down.

Some of the base's conventions are already true everywhere and need a guard so they stay that way;
others are true almost everywhere, and the README states them anyway. Both are held the same way
here — the sites are enumerated and frozen — because the two only differ by today's number.

A frozen count is not a suppression. A suppression makes a rule stop applying to a site; a freeze
makes the site *visible*, in one list, with the number that has to reach zero for the README's
sentence to become plainly true. The tell is direction: nothing here may grow without an edit to
this file, and every edit to these numbers is a decision someone made on purpose.

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

# Deep links the browser driver still takes instead of following a link or submitting a form,
# split by the Gherkin step that reaches them — because the step is what decides whether a URL is
# a shortcut or the scenario itself.
#
# A `given` may navigate: arranging a state is not what the scenario is about, and a driver that
# clicked its way through five pages of setup would be testing the setup. A `when` may navigate
# when the URL is genuinely where a person arrives from outside the app — a mailed confirmation
# link, an OAuth callback, an invitation token, an anonymous visitor typing an address, a machine
# endpoint. The base already reasons this way (`confirm_address_via_link` calls its own goto "the
# one legitimate goto").
#
# A `then` may never navigate, and that is the list below. An assertion that fetches its own page
# by URL asserts about a page nobody reached: it passes while the app's own route to that page is
# broken, which is the failure the browser lane exists to catch. Thirty-nine methods, and the
# only direction this set may move is smaller.
_NAVIGATES_UNDER_AN_ASSERTION = {
    "api_keys.assert_api_key_secret_revealed",
    "auth.assert_oauth_not_offered",
    "auth.assert_oauth_offered",
    "auth.assert_page_accessible",
    "auth.assert_passkey_listed",
    "auth.assert_passkey_signin_not_offered",
    "auth.assert_passkey_signin_offered",
    "auth.assert_twofa_enabled",
    "auth.assert_twofa_not_offered",
    "auth.open_accounts_screen",
    "calendar._cal_goto",
    "console._goto_admins",
    "console.assert_can_open_console",
    "console.assert_refused_console",
    "console.open_console_settings",
    "files._goto_files",
    "issues.open_issues_screen",
    "learning._goto_today",
    "learning.assert_no_resources",
    "learning.assert_resources",
    "organizations._goto_members",
    "organizations._overview_text",
    "organizations._read_org_cards_from_profile",
    "organizations.assert_is_owner",
    "organizations.assert_workspace_card",
    "pages._goto_list",
    "pages._goto_nav_manager",
    "pages.assert_cannot_edit",
    "pages.assert_view_contains",
    "pages.assert_visitor_can_view",
    "profile.assert_account_deletion_not_offered",
    "profile.assert_avatar_not_offered",
    "profile.assert_avatar_shown",
    "profile.assert_email_change_not_offered",
    "profile.assert_email_read_only",
    "profile.assert_handle",
    "profile.assert_handle_not_offered",
    "timeline.open_timeline",
    "todo.assert_completion_badge",
}

# Deep links reached only from `given` and `when`. Frozen as a total rather than a list: each one
# is a case-by-case judgement (is this URL arrived at from outside?), so the number is here to
# stop the count growing while the set above is worked down.
_DEEP_LINKS_ELSEWHERE = 57

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

    assert under_assertion == _NAVIGATES_UNDER_AN_ASSERTION


def test_the_deep_links_outside_assertions_do_not_grow():
    """Setup and action navigations, counted rather than listed: each is its own judgement about
    whether a person would really arrive at that URL from outside the app."""
    elsewhere = sum(count for kinds, count in _mixin_navigations().values() if "then" not in kinds)

    assert elsewhere == _DEEP_LINKS_ELSEWHERE


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
