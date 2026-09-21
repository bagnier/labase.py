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
from typing import TypeGuard

from tests.meta.readme import text as readme

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"

# The demos are meant to be deleted, and these are the non-demo modules that would break the day
# one is: the two e2e drivers composing every app's mixins, the rule books and the dev seed. Each
# is a coupling the base has chosen over a registration; the list only shrinks, since a demo
# deleted with any of these still in place takes the harness down with it. Two readers are left
# out on purpose: the composition root, whose job is to mount every app, and this package, which
# reads the reference app to hold the README's word on it.
_REACHES_INTO_A_DEMO = {
    "scripts/seed.py": {"todo"},
    "tests/e2e/drivers/api.py": {"calendar", "files", "learning", "todo"},
    "tests/e2e/drivers/browser.py": {"calendar", "files", "learning", "todo"},
    "tests/rulebooks.py": {"files", "learning"},
}

# The clock's own module, and the six test-side stamps that record *when the test asked*, which is
# a fact about the run and not about the domain — pinning them to the domain clock would make a
# mail-arrival window compare a real timestamp with a frozen one.
_MAY_READ_THE_WALL_CLOCK = ("apps/shared/clock.py", "/tests/")

# The logs subsystem computes the name it writes (the dependency verdict picks `…_failed` or
# `…_unreachable`, the chain re-emits whatever a library named its record). Everywhere else the
# name is a literal, which is what makes it greppable and what the Timeline's `app` axis reads.
_NAMES_ITS_LINES_AT_RUNTIME = "apps/shared/logs/"

# Reads defending against a `None` a writer really can produce: GoTrue's raw sign-in answer, a
# contribution's optional `growth`, Starlette's optional headers, and two optional parameters. Each
# is an external shape or a declared option, not slack in one of our own annotations — which is the
# distinction the README's rule turns on. A sixth is a decision.
_DEFENSIVE_READS = {
    "apps/auth/domain/service.py": 1,
    "apps/console/infra/router.py": 1,
    "apps/shared/charts.py": 1,
    "apps/shared/http/exceptions.py": 1,
    "apps/shared/queue.py": 1,
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

# Requests the driver fires itself instead of clicking. Seven of the nine are the base's own answer
# to "hiding the control is not proof": the affordance is absent or disabled for this actor, so the
# request it would have sent is fired from their own authenticated context and the server has to
# be the one refusing. The other two are the smell the README warns about, written down rather
# than left implicit.
_ASKS_THE_SERVER_DIRECTLY = {
    "organizations._probe_blocked": "the shared probe: the hidden control's own request, so a "
    "refusal is the server's and not the template's",
    "organizations.try_create_org": "the create request, so the owned-org limit is enforced by "
    "the server",
    "pages.try_publish_to_members": "the visibility request a member has no control for",
    "console.try_set_console_setting": "the settings request a non-admin has no control for",
    "console.assert_refused_console": "the console request the missing button would have sent",
    "console.revoke_server_admin": "the revoke PUT the UI disables for the last admin, so the "
    "guard is proven the server's and not the button's",
    "console.try_designate_server_admin": "the grant PUT a non-admin has no control for",
    "learning.want_to_learn": "the subscribe POST, fired by hand from a `given` arranging a "
    "scenario about reviewing rather than about subscribing. The other site here that is a smell",
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

# Every test double in the two e2e lanes, counted per file — "Nothing business-critical is
# mocked" holds because this list is what it is. The clock pin is the sanctioned time control
# (both drivers run the app in-process, so one setattr pins every `clock.now()`); the
# browser-launch tests steer the env var that picks a Chromium — ambient control, not a double.
_E2E_DOUBLES = {
    "tests/e2e/drivers/test_browser_launch.py": 3,
    "tests/plugin.py": 1,
}

# The API driver re-routes the three session dependencies onto the scenario's rolled-back
# transaction — a real database reached differently, and the browser lane runs the untouched app.
_SESSION_OVERRIDES = {
    "tests/e2e/drivers/api_base.py": 3,
}

# The one router allowed to drive the database itself: the readiness probe's whole job is to
# touch the dependency and report, so its `select 1` has nowhere lower to live.
_ROUTERS_TOUCHING_THE_DB = {
    "apps/health/router.py",
}

# Request functions on the BYPASSRLS session, counted per module. The README reserves
# `AdminSession` for event handlers, console queries and anonymous public surfaces; this is what
# that reservation costs today, so widening it is an edit someone makes on purpose.
_BYPASSRLS_PARAMETERS = {
    "apps/auth/infra/accounts_router.py": 4,
    "apps/auth/infra/router.py": 12,
    "apps/console/infra/router.py": 13,
    "apps/files/infra/router.py": 1,
    "apps/issues/infra/router.py": 3,
    "apps/metrics/infra/router.py": 1,
    "apps/organizations/infra/invitation_router.py": 2,
    "apps/pages/infra/router.py": 3,
    "apps/profile/infra/router.py": 1,
    "apps/public/infra/router.py": 2,
    "apps/tasks/infra/router.py": 2,
    "apps/timeline/infra/router.py": 3,
}

# Class selectors defined outside `@layer components` in `static/css/input.css`. Everything here
# is plain CSS that beats the layered components in the cascade — `list-panel` and `paper` are
# even *redefinitions* of layered classes — which is the inversion the README's "one component
# system" forbids. The list only shrinks: moving one into the layer is the fix, adding one here
# is a decision.
_OUTSIDE_THE_COMPONENT_LAYER = {
    "activity-timeline",
    "cm-toolbar",
    "cm-toolbar-btn",
    "cm-toolbar-sep",
    "flip",
    "heatmap",
    "heatmap-cell",
    "heatmap-col",
    "heatmap-col-label",
    "heatmap-day",
    "heatmap-month",
    "heatmap-swatch",
    "lcard",
    "list-panel",
    "paper",
    "ph",
    "saved-flash",
    "scene",
    "strip-attempt",
    "strip-axis",
    "strip-block",
    "strip-done",
    "strip-grid",
    "strip-gridlines",
    "strip-group",
    "strip-lane",
    "strip-name",
    "strip-parked",
    "strip-pending",
    "strip-retrying",
    "strip-row",
    "strip-swatch",
    "strip-tail",
    "task-bar",
    "task-sub",
    "task-total",
}

_SNAPSHOT_READS = {
    "all",
    "content",
    "count",
    "get_attribute",
    "inner_html",
    "inner_text",
    "input_value",
    "is_checked",
    "is_enabled",
    "text_content",
}

# Per browser mixin, the snapshot reads its assertions still make. None is a `count()`: those are
# `expect(...).to_have_count(n)` now. What is left reads text or an attribute once — the backlog
# of `expect-not-is-visible`, and it only shrinks.
_SNAPSHOT_READS_IN_ASSERTIONS = {
    "apps/auth/tests/e2e/driver_mixin_browser.py": 4,
    "apps/calendar/tests/e2e/driver_mixin_browser.py": 4,
    "apps/console/tests/e2e/driver_mixin_browser.py": 7,
    "apps/files/tests/e2e/driver_mixin_browser.py": 1,
    "apps/issues/tests/e2e/driver_mixin_browser.py": 3,
    "apps/learning/tests/e2e/driver_mixin_browser.py": 9,
    "apps/metrics/tests/e2e/driver_mixin_browser.py": 5,
    "apps/organizations/tests/e2e/driver_mixin_browser.py": 2,
    "apps/pages/tests/e2e/driver_mixin_browser.py": 11,
    "apps/profile/tests/e2e/driver_mixin_browser.py": 1,
    "apps/timeline/tests/e2e/driver_mixin_browser.py": 1,
    "apps/todo/tests/e2e/driver_mixin_browser.py": 2,
}

_STEP_TYPES = {"given", "when", "then"}
# What Playwright's request context can send: ``context.request.put(...)``, ``page.request.fetch``.
_REQUEST_VERBS = {"fetch", "get", "post", "put", "patch", "delete", "head"}
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


# Which imported binding lands in which bucket of `_clock_bindings`.
_CLOCK_MODULE_BUCKET = {"datetime": "datetime_module", "time": "time_module"}
_CLOCK_FROM_BUCKET = {
    ("datetime", "datetime"): "datetime",
    ("datetime", "date"): "date",
    ("time", "time"): "bare_time",
}


def _clock_bindings(tree: ast.Module) -> tuple[dict[str, set[str]], list[int]]:
    """What this module's imports bind the clock-shaped names to, bucketed — plus the lines that
    import the clock's `now` by value, a stray in themselves."""
    bound: dict[str, set[str]] = {
        "datetime": {"datetime"},
        "date": {"date"},
        "datetime_module": set(),
        "time_module": set(),
        "bare_time": set(),
    }
    stray_imports = []
    for node in ast.walk(tree):
        aliases = node.names if isinstance(node, ast.Import | ast.ImportFrom) else []
        for alias in aliases:
            name = alias.asname or alias.name
            if isinstance(node, ast.Import) and alias.name in _CLOCK_MODULE_BUCKET:
                bound[_CLOCK_MODULE_BUCKET[alias.name]].add(name)
            elif isinstance(node, ast.ImportFrom):
                imported = (node.module or "", alias.name)
                if imported in _CLOCK_FROM_BUCKET:
                    bound[_CLOCK_FROM_BUCKET[imported]].add(name)
                elif imported == ("apps.shared.clock", "now"):
                    stray_imports.append(node.lineno)
    return bound, stray_imports


def _is_wall_clock_call(node: ast.Call, bound: dict[str, set[str]]) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in bound["bare_time"]
    if not isinstance(func, ast.Attribute):
        return False
    target = func.value
    named = target.id if isinstance(target, ast.Name) else None
    module_member = (
        target.attr
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id in bound["datetime_module"]
        else None
    )
    if func.attr in {"now", "utcnow"}:
        return named in bound["datetime"] or module_member == "datetime"
    if func.attr == "today":
        return named in bound["date"] or module_member == "date"
    return func.attr == "time" and named in bound["time_module"]


def _wall_clock_reads(tree: ast.Module) -> list[int]:
    """Line numbers of every wall-clock read in one module — `datetime.now`/`utcnow`,
    `date.today` and `time.time` through any import alias, plus the clock's own `now` imported
    by value, which a patch of `apps.shared.clock.now` never reaches. `time.monotonic` and
    `perf_counter` measure durations, not the wall, and stay allowed."""
    bound, reads = _clock_bindings(tree)
    return reads + [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_wall_clock_call(node, bound)
    ]


def test_time_comes_from_the_one_clock():
    """A second reading of the wall clock is how a test that pins time stops pinning anything —
    and `from apps.shared.clock import now` is the same leak one step removed: bound by value,
    the reader keeps the function the harness's patch of the clock module no longer names."""
    strays = {
        f"{relative}:{line}"
        for path, relative in _python_files(_APPS)
        if not any(allowed in f"/{relative}" for allowed in _MAY_READ_THE_WALL_CLOCK)
        for line in _wall_clock_reads(ast.parse(path.read_text()))
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
    """`locator.is_visible()` reads the DOM once, at whatever moment an HTMX swap happens to be
    in. `expect(...)` retries to the settled state. The read is what is banned, not the line
    shape: an `if loc.is_visible(): return` or a bound `seen = loc.is_visible` is the same
    snapshot with the `assert` moved elsewhere."""
    reads = {
        f"{relative}:{node.lineno}"
        for path, relative in _python_files(_APPS, _ROOT / "tests")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Attribute) and node.attr in {"is_visible", "is_hidden"}
    }

    assert reads == set()


def _snapshot_reads_in_assertions(path: Path) -> int:
    """Snapshot DOM reads inside a mixin's ``assert_*`` methods — each one is compared once, at
    whatever state the page happens to be in, where ``expect(...)`` would retry to the settled
    one."""
    return sum(
        1
        for fn in ast.walk(ast.parse(path.read_text()))
        if isinstance(fn, ast.FunctionDef) and fn.name.startswith("assert_")
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _SNAPSHOT_READS
    )


def test_the_snapshot_reads_in_assertions_are_the_named_ones():
    """The half of `expect-not-is-visible` a banned spelling cannot reach: a `count() == 0` read
    before a swap lands passes however wrong the page is about to be. `count` is gone; the reads
    left compare text or attributes, and only shrink."""
    reads = {
        str(mixin.relative_to(_ROOT)): found
        for mixin in sorted(_APPS.glob("*/tests/e2e/driver_mixin_browser.py"))
        if (found := _snapshot_reads_in_assertions(mixin))
    }

    assert reads == _SNAPSHOT_READS_IN_ASSERTIONS


def _called_attributes(fn: ast.AST) -> list[str]:
    """Every ``x.name(...)`` called inside ``fn``, by attribute name."""
    return [
        node.func.attr
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]


def _mixin_methods(mixin: Path) -> tuple[dict[str, int], dict[str, set[str]]]:
    """``({method: goto calls}, {method: methods it calls})`` for one browser mixin — its class
    bodies and its module-level functions alike, since a helper hoisted out of the class navigates
    just the same."""
    gotos, calls = {}, {}
    for node in ast.parse(mixin.read_text()).body:
        functions = node.body if isinstance(node, ast.ClassDef) else [node]
        for fn in functions:
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


def _step_navigations(steps: Path) -> dict[str, tuple[set[str], int]]:
    """``{steps.function: (its step types, goto calls)}`` — a step that navigates itself, without
    going through the driver, is a navigation no mixin walk would ever see."""
    found = {}
    if not steps.exists():
        return found
    for fn in ast.walk(ast.parse(steps.read_text())):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        kinds = {
            decorator.func.id
            for decorator in fn.decorator_list
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name)
        } & _STEP_TYPES
        if count := _called_attributes(fn).count("goto"):
            found[f"steps.{fn.name}"] = (kinds, count)
    return found


def _mixin_navigations() -> dict[str, tuple[set[str], int]]:
    """``{app.method: (step types that reach it, goto calls)}``, over every browser mixin and
    every step module beside one."""
    found = {}
    for mixin in sorted(_APPS.glob("*/tests/e2e/driver_mixin_browser.py")):
        app = mixin.relative_to(_APPS).parts[0]
        gotos, calls = _mixin_methods(mixin)
        reached = _propagated(_steps_reaching(mixin.parent / "steps.py"), calls)
        found |= {f"{app}.{name}": (reached[name], count) for name, count in gotos.items() if count}
        found |= {
            f"{app}.{name}": reach
            for name, reach in _step_navigations(mixin.parent / "steps.py").items()
        }
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


def _is_a_request_call(node: ast.AST) -> bool:
    """``….fetch(…)``, or any verb on a request context — ``context.request.put(…)``."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    if node.func.attr == "fetch":
        return True
    return (
        node.func.attr in _REQUEST_VERBS
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "request"
    )


def _fires_its_own_request(fn: ast.AST) -> bool:
    """Does this method send a request rather than click? Either through Playwright's own
    request context — ``fetch``, or a verb on ``….request`` — or through a ``fetch(`` written into
    a script it evaluates in the page."""
    return any(
        _is_a_request_call(node)
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


def test_the_e2e_doubles_are_the_named_ones():
    """ "Nothing business-critical is mocked" — held as the complete, counted list of what the
    two e2e lanes double: the pinned clock and the driver's own env control, plus the API lane's
    session overrides. GoTrue, Postgres, Storage and the mail catcher are all real; a new double
    lands here as a question."""
    doubles = _sites(
        r"monkeypatch\.(setattr|setenv|delenv|setitem)|\bMagicMock\b|\bMock\(|mock\.patch",
        _ROOT / "tests",
        *sorted(_APPS.glob("*/tests/e2e")),
    )

    overrides = _sites(
        r"dependency_overrides\[", _ROOT / "tests", *sorted(_APPS.glob("*/tests/e2e"))
    )

    assert (doubles, overrides) == (_E2E_DOUBLES, _SESSION_OVERRIDES)


def _db_touches_in_routers() -> set[str]:
    """Router modules that reach the database themselves — a DML/select/text import from
    sqlalchemy (typing and exception imports stay free), or a session driven directly."""
    dml = {"select", "insert", "update", "delete", "text", "func", "literal"}
    driving = {"execute", "scalar", "scalars", "add", "add_all", "merge", "flush"}
    touching = set()
    for path in [*sorted(_APPS.glob("*/infra/*router*.py")), _APPS / "health" / "router.py"]:
        relative = str(path.relative_to(_ROOT))
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.ImportFrom)
                and (node.module or "").split(".")[0] == "sqlalchemy"
                and any(alias.name in dml for alias in node.names)
            ):
                touching.add(relative)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in driving
                and isinstance(node.func.value, ast.Name)
                and "session" in node.func.value.id
            ):
                touching.add(relative)
    return touching


def test_no_router_reaches_the_database_itself():
    """The mechanical half of "Routers own HTTP and nothing else": no DML import, no session
    driven from a router — that goes through a repository. The business-logic half stays a
    review question; the readiness probe is the one named exception."""
    assert _db_touches_in_routers() == _ROUTERS_TOUCHING_THE_DB


def test_the_bypassrls_parameters_are_the_counted_ones():
    """The distance between "AdminSession is reserved for…" and today, as a number per module.
    This is the ratchet the `python-never-reimplements-isolation` waiver names: every request
    function on the BYPASSRLS session is one place Python may be re-deciding what RLS should."""
    parameters = {}
    for path, relative in _python_files(_APPS):
        if "/tests/" in relative:
            continue
        count = sum(
            1
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.arg)
            and node.annotation is not None
            and "AdminSession" in ast.unparse(node.annotation)
        )
        if count:
            parameters[relative] = count

    assert parameters == _BYPASSRLS_PARAMETERS


def _component_layer_span(css: str) -> tuple[int, int]:
    opening = css.index("{", css.index("@layer components"))
    depth = 0
    for position in range(opening, len(css)):
        if css[position] == "{":
            depth += 1
        elif css[position] == "}":
            depth -= 1
            if depth == 0:
                return opening, position
    return opening, len(css)


def test_the_classes_outside_the_component_layer_are_the_named_ones():
    """The ratchet the `one-component-system` waiver names: a class defined in plain CSS outside
    `@layer components` beats every layered component in the cascade, whatever the specificity —
    the inversion behind `paper border-2` computing 1px. The set may only shrink."""
    css = (_ROOT / "static" / "css" / "input.css").read_text()
    start, end = _component_layer_span(css)

    outside = {
        selector.group(1)
        for selector in re.finditer(r"^\s*\.([a-zA-Z][\w-]*)", css, flags=re.MULTILINE)
        if not start <= selector.start() <= end
    }

    assert outside == _OUTSIDE_THE_COMPONENT_LAYER


def test_nothing_reruns_a_failing_test():
    """ "Everything else is strict, zero rerun" — kept true the cheap way: the plugin that could
    rerun anything is not installed, no lane pulls it in at run time (`uv run --with`), and no
    hook of ours takes over the run protocol, which is the one place a rerun could be written by
    hand and reported as a pass."""
    pyproject = (_ROOT / "pyproject.toml").read_text()
    lanes = "\n".join(
        (_ROOT / name).read_text() for name in ("Makefile", ".github/workflows/ci.yml")
    )

    hooks = _sites(r"def pytest_runtest_protocol\b", _ROOT / "tests", _APPS)

    assert (
        "pytest-rerunfailures" in pyproject,
        "--reruns" in pyproject,
        "rerunfailures" in lanes,
        "--reruns" in lanes,
        hooks,
    ) == (False, False, False, False, {})


def _demos() -> set[str]:
    """The contexts the README's demo table lists — what "meant to be deleted" applies to."""
    table = readme()[readme().index("| Demo") :]
    return set(re.findall(r"^\| `(\w+)/`", table[: table.index("\n\n")], re.MULTILINE))


def _demos_imported_by(path: Path, demos: set[str]) -> set[str]:
    imported = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        elif isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        else:
            continue
        for module in modules:
            parts = module.split(".")
            if parts[:1] == ["apps"] and len(parts) > 1 and parts[1] in demos:
                imported.add(parts[1])
    return imported


def test_the_modules_outside_a_demo_that_import_it_are_the_named_ones():
    """The ratchet the `demo-apps-are-disposable` and `apps-are-self-contained` waivers name: an
    import of a demo from anywhere but the demo itself or the composition root is a module that
    stops loading the day the demo is deleted. Frozen per module, and only the import edge — a
    template hard-coding a demo's name is the half a walk over imports cannot see."""
    demos = _demos()
    reaching = {
        relative: imported
        for path, relative in _python_files(_APPS, _ROOT / "tests", _ROOT / "scripts")
        if relative != "apps/main.py"
        and not (path.is_relative_to(_APPS) and path.relative_to(_APPS).parts[0] in demos)
        and (imported := _demos_imported_by(path, demos))
    }

    assert (demos, reaching) == ({"calendar", "files", "learning", "todo"}, _REACHES_INTO_A_DEMO)


# ── No magic number ─────────────────────────────────────────────────────────────────────────────
#
# Every numeric literal in ``apps/`` bound to a module constant or to a parameter's default —
# the two shapes a tuning knob takes when it is not a setting. Three groups, because the sentence
# forbids one thing and not the other two, and only the third is a backlog.

# The literal *is* the setting's declared fallback: the console owns the live value and this is
# what it falls back to. Exactly what the principle asks for, so it never leaves this list.
_DEFAULTS_OF_A_DECLARED_SETTING = {
    "apps/shared/persistence/sql_stats.py::DEFAULT_HEAVY_MS = 500",
    "apps/shared/persistence/sql_stats.py::DEFAULT_HEAVY_QUERIES = 30",
}

# Numbers that are not knobs: a status code carries the response's meaning, an SVG dimension is
# the drawing, 53 is how many weeks a year can hold, a fingerprint's frame count and truncation
# lengths *are* the fingerprint (moving one silently re-groups every past issue), and 9 is the
# rung count of the spaced-repetition ladder itself. Turning any of these into a setting would
# offer an operator a lever that breaks the thing rather than tunes it.
_NOT_A_TUNING_KNOB = {
    "apps/issues/domain/service.py::_STACK_MAX = 8000",
    "apps/issues/domain/service.py::_TITLE_MAX = 200",
    "apps/issues/domain/service.py::_TOP_FRAMES = 5",
    "apps/learning/domain/service.py::MAX_LEVEL = 9",
    "apps/profile/infra/router.py::_profile_error(status_code=400)",
    "apps/shared/charts.py::day_buckets_series(height=240)",
    "apps/shared/charts.py::sparkline(height=48)",
    "apps/shared/events/activity.py::heatmap_calendar(max_weeks=53)",
    "apps/shared/events/activity.py::heatmap_calendar(min_weeks=5)",
    "apps/shared/events/repository.py::search(offset=0)",
    "apps/shared/http/responses.py::mutation_response(status_code=200)",
    "apps/shared/persistence/sql_stats.py::_KEPT_STATEMENTS = 5",
    "apps/shared/persistence/sql_stats.py::_MAX_STATEMENT = 300",
    "apps/tasks/domain/strip.py::_MAX_BUCKETS = 400",
    "apps/tasks/domain/strip.py::_MAX_TICKS = 8",
    "apps/tasks/domain/strip.py::_MIN_SHARE = 6.0",
    "apps/tasks/domain/strip.py::_MIN_WIDTH = 0.4",
}

# The backlog the sentence names: retention windows, poll and purge intervals, retry budgets,
# batch sizes, page lengths, deadlines and caps — each one a value an operator has a reason to
# change and today can only change by editing Python. This list only shrinks; a promotion to
# `TechnicalSettings` or to an app's declared settings removes a line, and nothing adds one
# without someone deciding to here.
_KNOBS_AWAITING_PROMOTION = {
    "apps/api_keys/infra/repository.py::_LAST_USED_GRANULARITY_SECONDS = 300",
    "apps/auth/contract/impersonation.py::IMPERSONATION_MAX_SECONDS = 3600",
    "apps/auth/infra/accounts_router.py::_PAGE_SIZE = 1000",
    "apps/auth/infra/router.py::_MFA_MAX_SECONDS = 300",
    "apps/auth/infra/router.py::_OAUTH_MAX_SECONDS = 300",
    "apps/auth/infra/user_repository.py::_PAGE_SIZE = 1000",
    "apps/calendar/contract/integration.py::_RECENT = 3",
    "apps/console/infra/router.py::_GROWTH_DAYS = 14",
    "apps/files/contract/integration.py::_RECENT = 3",
    "apps/issues/contract/integration.py::CAPTURE_DRAIN_SECONDS = 1.0",
    "apps/issues/contract/integration.py::PURGE_EVERY_SECONDS = 86400",
    "apps/issues/contract/queries.py::search_issue_occurrences(limit=100)",
    "apps/issues/infra/repository.py::list_issues(limit=100)",
    "apps/issues/infra/repository.py::occurrences(limit=20)",
    "apps/issues/infra/router.py::_SPARK_DAYS = 14",
    "apps/metrics/contract/integration.py::MINUTE_RETENTION_DAYS = 7",
    "apps/metrics/contract/integration.py::ROLLUP_EVERY_SECONDS = 86400",
    "apps/metrics/domain/accumulator.py::UNMATCHED_LABEL_CAP = 25",
    "apps/metrics/domain/service.py::percentile_ms(quantile=0.95)",
    "apps/metrics/infra/router.py::WINDOW_HOURS = 24",
    "apps/organizations/contract/queries.py::list_org_handles(limit=500)",
    "apps/organizations/infra/router.py::_ACTIVITY_MAX = 250",
    "apps/organizations/infra/router.py::_ACTIVITY_PAGE = 8",
    "apps/pages/contract/integration.py::_RECENT = 3",
    "apps/profile/contract/integration.py::_GROWTH_DAYS = 14",
    "apps/profile/infra/router.py::_ACTIVITY_MAX = 250",
    "apps/profile/infra/router.py::_ACTIVITY_PAGE = 25",
    "apps/profile/infra/router.py::_ENROLLMENT_MAX_SECONDS = 300",
    "apps/shared/events/listener.py::SPREAD_SETTLE_SECONDS = 60.0",
    "apps/shared/events/listener.py::__init__(batch_size=50)",
    "apps/shared/events/repository.py::daily_counts(days=366)",
    "apps/shared/events/repository.py::search(limit=100)",
    "apps/shared/http/limiter.py::PURGE_EVERY_SECONDS = 3600",
    "apps/shared/logs/repository.py::search(limit=100)",
    "apps/shared/queue.py::QUEUE_PURGE_EVERY_SECONDS = 86400",
    "apps/shared/queue.py::QUEUE_RETENTION_DAYS = 7",
    "apps/shared/queue.py::_RETRY_BACKOFF_SECONDS = 60",
    "apps/shared/queue.py::_VISIBILITY_TIMEOUT_SECONDS = 300",
    "apps/shared/queue.py::__init__(batch_size=10)",
    "apps/shared/queue.py::enqueue(max_attempts=5)",
    "apps/shared/queue.py::list_unfinished_tasks(limit=200)",
    "apps/timeline/contract/integration.py::PURGE_EVERY_SECONDS = 86400",
    "apps/timeline/infra/repository.py::activity(cap=20000)",
    "apps/timeline/infra/repository.py::facets(cap=2000)",
    "apps/timeline/infra/repository.py::search(limit=100)",
    "apps/timeline/infra/router.py::_EXPORT_LIMIT = 5000",
    "apps/timeline/infra/router.py::_PAGE_SIZE = 100",
    "apps/todo/contract/integration.py::_RECENT = 3",
}


def _numeric_literals(tree: ast.AST, relative: str) -> set[str]:
    """Numeric literals in the two places a knob hides: bound to a module-level name, or standing
    as a parameter's default. A literal inside an expression is arithmetic, not configuration, and
    is deliberately out of scope — the rule is about values someone would want to change."""
    found = set()
    for node in getattr(tree, "body", []):
        target, value = None, None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and _is_number(value):
            found.add(f"{relative}::{target.id} = {value.value}")
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        args = node.args
        positional = args.args[len(args.args) - len(args.defaults) :]
        # Both pairings are equal-length by construction: a default per trailing positional,
        # and one slot per keyword-only argument, holding ``None`` where it has no default.
        pairs = [
            *zip(args.defaults, positional, strict=True),
            *zip(args.kw_defaults, args.kwonlyargs, strict=True),
        ]
        found |= {
            f"{relative}::{node.name}({arg.arg}={default.value})"
            for default, arg in pairs
            if _is_number(default)
        }
    return found


def _is_number(node: ast.AST | None) -> TypeGuard[ast.Constant]:
    """A numeric literal — narrowing to ``ast.Constant``, so each caller reads ``.value`` off a
    node the checker knows it has. A bool is an ``int`` in Python and a flag to a reader, so it
    is not a magic number."""
    if not isinstance(node, ast.Constant):
        return False
    return isinstance(node.value, int | float) and not isinstance(node.value, bool)


def test_the_numbers_outside_the_settings_are_the_named_ones():
    """ "No magic number" — held as the enumerated list of what is left, since the sentence is an
    aim and the list is its distance. Every literal below is either a setting's own default, a
    number that is not a knob at all, or a knob nobody has promoted yet; a new one belongs to one
    of the three by an edit here, which is the decision the README says someone has to make."""
    found = {
        entry
        for path, relative in _python_files(_APPS)
        if "/tests/" not in relative
        for entry in _numeric_literals(ast.parse(path.read_text()), relative)
    }

    assert found == (
        _DEFAULTS_OF_A_DECLARED_SETTING | _NOT_A_TUNING_KNOB | _KNOBS_AWAITING_PROMOTION
    )
