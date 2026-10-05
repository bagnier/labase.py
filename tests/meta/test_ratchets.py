"""AGENTS.md's absolute rules, held as frozen lists of the sites left, each with its reason. A
list may only shrink; adding to it is a decision made here. A claim whose ratchet is not at zero
stays waived in ``tests/meta/claims.py``.
"""

import ast
import re
from collections import defaultdict
from pathlib import Path
from typing import TypeGuard

from tests.meta.readme import text as readme

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"

# Non-demo modules that break when a demo is deleted: the drivers composing every mixin, the rule
# books, the dev seed. Exempt: the composition root, and this package, reading the reference app.
_REACHES_INTO_A_DEMO = {
    "scripts/seed.py": {"todo"},
    "tests/e2e/drivers/api.py": {"calendar", "files", "learning", "todo"},
    "tests/e2e/drivers/browser.py": {"calendar", "files", "learning", "todo"},
    "tests/rulebooks.py": {"files", "learning"},
}

# The clock itself, and the test-side stamps of when a test asked (a mail-arrival window must
# compare real times, not a frozen one).
_MAY_READ_THE_WALL_CLOCK = ("apps/shared/clock.py", "/tests/")

# The logs subsystem computes its line names (the verdict, a library's record); elsewhere a name
# is a literal, greppable.
_NAMES_ITS_LINES_AT_RUNTIME = "apps/shared/logs/"

# Reads tolerating a `None` (`or`, `typing.cast`, a suppression), by function. Each answers a shape
# from outside (an aggregate over no rows, GoTrue, Starlette, SQLAlchemy, pydantic-settings), not
# slack in our own annotations (AGENTS: `| None` means optional).
_DEFENSIVE_READS = [
    "apps/auth/domain/service.py::confirm_signup cast",
    'apps/auth/domain/service.py::exchange_oauth_code or ""',
    "apps/auth/domain/service.py::exchange_oauth_code or {}",
    "apps/auth/domain/service.py::list_passkeys or []",
    "apps/auth/domain/service.py::verified_totp_factor or []",
    'apps/auth/infra/accounts_router.py::_list_accounts or ""',
    'apps/auth/infra/router.py::impersonate_endpoint or ""',
    'apps/auth/infra/router.py::login_page or ""',
    'apps/auth/infra/router.py::mfa_verify_endpoint or ""',
    'apps/auth/infra/router.py::oauth_callback or ""',
    'apps/auth/infra/user_repository.py::list_server_admins or ""',
    'apps/auth/infra/user_repository.py::resolve_user_emails._get or ""',
    "apps/console/contract/integration.py::mount cast",
    'apps/console/domain/studio.py::studio_base_url or ""',
    "apps/console/infra/router.py::_growth_chart or {}",
    "apps/files/infra/repository.py::OrgFileRepository.total_size or 0",
    'apps/files/infra/storage.py::signed_redirect_url or ""',
    'apps/issues/domain/service.py::status_after_occurrence or ""',
    "apps/issues/infra/repository.py::purge_old_occurrences or 0",
    "apps/metrics/infra/repository.py::purge or 0",
    "apps/metrics/infra/repository.py::total_requests or 0",
    'apps/organizations/infra/router.py::_emit_last_owner_violation or ""',
    'apps/pages/domain/render.py::render_markdown or ""',
    "apps/pages/infra/repository.py::PageNavRepository.add or 0",
    'apps/profile/infra/router.py::avatar_upload or ""',
    'apps/profile/infra/router.py::avatar_upload or ""',
    "apps/public/contract/integration.py::_console_overview ignore",
    "apps/public/infra/router.py::_featured_org ignore",
    "apps/public/infra/router.py::public_page ignore",
    "apps/shared/charts.py::day_buckets_series or {}",
    "apps/shared/http/exceptions.py::handle_http_error or {}",
    "apps/shared/http/limiter.py::_increment or 0",
    "apps/shared/http/templates.py::<module> cast",
    "apps/shared/logs/repository.py::LogRepository.roll or 0",
    'apps/shared/logs/repository.py::_columns or ""',
    'apps/shared/logs/repository.py::_columns or ""',
    "apps/shared/persistence/repository.py::BaseRepository.all cast",
    "apps/shared/persistence/repository.py::BaseRepository.get cast",
    "apps/shared/persistence/repository.py::OrgScopedRepository.all cast",
    "apps/shared/persistence/repository.py::OrgScopedRepository.get cast",
    "apps/shared/persistence/repository.py::OrgScopedRepository.recent cast",
    "apps/shared/persistence/repository.py::PositionedRepository.move_above cast",
    "apps/shared/persistence/repository.py::count_where or 0",
    "apps/shared/queue.py::TaskWorker.tick cast",
    "apps/shared/queue.py::enqueue or {}",
    "apps/shared/queue.py::purge_finished_tasks or 0",
    "apps/shared/settings/env.py::get_technical_settings ignore",
    "apps/tasks/infra/router.py::_history_json cast",
    "apps/tasks/infra/router.py::_history_json cast",
    "apps/tasks/infra/router.py::_history_json cast",
    "apps/timeline/contract/integration.py::mount cast",
    'apps/timeline/infra/repository.py::_from_issue or ""',
    'apps/timeline/infra/repository.py::_sort_value or ""',
]

# The browser mixins' URL navigations, each an arrival from outside the app (front door, mailed
# link, invitation, a stranger's typed address, a machine endpoint, a download); everything else is
# clicked. A `then` never navigates (``test_no_assertion_step_reaches_a_page_by_url``).
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

# Requests the driver sends instead of clicking. Seven prove the server refuses what a hidden
# control would send; the other two are the smell AGENTS.md names, written down.
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

# The driver base's own navigations: each scenario's entry point, and the isolation tests.
_SUBSTRATE_DEEP_LINKS = {
    "tests/e2e/drivers/browser_base.py": 2,
    "tests/e2e/drivers/test_browser_isolation.py": 2,
}

# Every test double under `tests/`: the clock pin, the env var picking a Chromium, the
# environment `apply_host_overrides` reads. Ambient control, not doubles of business code.
_E2E_DOUBLES = {
    "tests/e2e/drivers/test_browser_launch.py": 3,
    "tests/plugin.py": 1,
    "tests/test_envfile.py": 2,
    "tests/test_promote_admin.py": 2,
}

# The API driver's session overrides: the real database, through the rolled-back transaction.
_SESSION_OVERRIDES = {
    "tests/e2e/drivers/api_base.py": 2,
}

# The readiness probe's `select 1` is its job.
_ROUTERS_TOUCHING_THE_DB = {
    "apps/health/router.py",
}

# `get_settings` in a router, where no dependency fits: the share download (org from the row) and
# the timeline settings screen (every declared setting, not effective values).
_ROUTERS_READING_SETTINGS_BY_STRING = {
    "apps/files/infra/router.py::public_share_download",
    "apps/timeline/infra/router.py::_settings_rows",
}

# Request functions on the BYPASSRLS session, per module (AGENTS: three sessions, and RLS by
# default).
_BYPASSRLS_PARAMETERS = {
    "apps/auth/infra/accounts_router.py": 5,
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

# Classes outside `@layer components` in `static/css/input.css`: they beat the layered components
# in the cascade (`list-panel` and `paper` redefine some). The fix moves them into the layer.
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

# Snapshot reads of text or attributes left in each browser mixin's assertions.
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

# Driver state a `when` sets and a `then` narrows with an assert: a lifecycle that belongs in one
# narrowing accessor, as `ApiBase.response` does.
_LIFECYCLES_THE_TESTS_NARROW = {
    "apps/api_keys/tests/e2e/driver_mixin_api.py": [
        "ApiKeysApiMixin._sessionless_get self._api_key_secret",
        "ApiKeysApiMixin.assert_api_key_secret_revealed self._api_key_secret",
        "ApiKeysApiMixin.create_org_with_api_key self._api_key_secret",
    ],
    "apps/api_keys/tests/e2e/driver_mixin_browser.py": [
        "ApiKeysBrowserMixin._sessionless_get self._api_key_secret",
        "ApiKeysBrowserMixin.assert_api_key_secret_revealed self._api_key_secret",
        "ApiKeysBrowserMixin.create_org_with_api_key self._api_key_secret",
    ],
    "apps/auth/tests/e2e/driver_mixin_api.py": [
        "AuthApiMixin._visitor_html self._visitor_page",
        "AuthApiMixin.assert_confirmation_delivered self._confirmation_requested_at",
        "AuthApiMixin.assert_registration_successful self.last_registered_email",
        "AuthApiMixin.confirm_address_via_link self._confirmation_requested_at",
        "AuthApiMixin.enter_totp_code self._mfa_challenge",
        "AuthApiMixin.enter_totp_code self._totp_secret",
        "AuthApiMixin.reset_password_via_email self._reset_email",
        "AuthApiMixin.reset_password_via_email self._reset_requested_at",
    ],
    "apps/auth/tests/e2e/driver_mixin_browser.py": [
        "AuthBrowserMixin.assert_confirmation_delivered self._confirmation_requested_at",
        "AuthBrowserMixin.assert_impersonation_refused self.last_response",
        "AuthBrowserMixin.assert_page_loaded self.last_response",
        "AuthBrowserMixin.assert_registration_failed self.last_response",
        "AuthBrowserMixin.assert_registration_successful self.last_registered_email",
        "AuthBrowserMixin.confirm_address_via_link self._confirmation_requested_at",
        "AuthBrowserMixin.enroll_totp self._totp_secret",
        "AuthBrowserMixin.enter_totp_code self._totp_secret",
        "AuthBrowserMixin.reset_password_via_email self._reset_email",
        "AuthBrowserMixin.reset_password_via_email self._reset_requested_at",
    ],
    "apps/auth/tests/given_helpers.py": [
        "create_unconfirmed_user resp.user",
        "create_user resp.user",
    ],
    "apps/auth/tests/test_auth_service.py": [
        "test_login_valid_credentials_returns_access_and_refresh_tokens tokens.access_token",
        "test_login_valid_credentials_returns_access_and_refresh_tokens tokens.refresh_token",
    ],
    "apps/calendar/tests/e2e/driver_mixin_api.py": [
        "CalendarApiMixin.assert_event_description self._cal_detail",
        "CalendarApiMixin.assert_event_location self._cal_detail",
        "CalendarApiMixin.assert_event_when self._cal_detail",
    ],
    "apps/calendar/tests/e2e/driver_mixin_browser.py": [
        "CalendarBrowserMixin.assert_event_rejected self.last_response",
    ],
    "apps/console/tests/e2e/driver_mixin_api.py": [
        "ConsoleApiMixin._as_admin self._admin_email",
        "ConsoleApiMixin.assert_console_setting_shown self.settings_response",
        "ConsoleApiMixin.assert_console_supabase_link self.settings_response",
    ],
    "apps/console/tests/e2e/driver_mixin_browser.py": [
        "ConsoleBrowserMixin._as_admin self._admin_acting",
    ],
    "apps/files/tests/e2e/driver_mixin_api.py": [
        "OrgFileApiMixin.access_share_link_as self.share_link_url",
        "OrgFileApiMixin.access_share_link_unauthenticated self.share_link_url",
    ],
    "apps/files/tests/e2e/driver_mixin_browser.py": [
        "OrgFileBrowserMixin.access_share_link_unauthenticated self.context",
        "OrgFileBrowserMixin.assert_action_rejected self.last_response",
        "OrgFileBrowserMixin.assert_download_succeeds self.last_response",
        "OrgFileBrowserMixin.assert_upload_rejected self.last_response",
    ],
    "apps/issues/tests/test_capture.py": [
        "test_log_exception_is_captured capture._QUEUE",
    ],
    "apps/learning/tests/e2e/driver_mixin_api.py": [
        "LearningApiMixin._current self._learn_current",
    ],
    "apps/learning/tests/e2e/driver_mixin_browser.py": [
        "LearningBrowserMixin._current self._learn_current",
    ],
    "apps/organizations/tests/e2e/driver_mixin_api.py": [
        "OrgApiMixin.assert_other_org_absent self._org_list_response",
    ],
    "apps/organizations/tests/e2e/driver_mixin_browser.py": [
        "OrgBrowserMixin.assert_action_fails_with self.last_response",
        "OrgBrowserMixin.assert_org_dashboard_visible self.last_response",
        "OrgBrowserMixin.assert_other_org_absent self._org_list_response",
    ],
    "apps/organizations/tests/test_emails.py": [
        "test_invitation_email_renders_both_bodies email.html",
    ],
    "apps/pages/tests/e2e/driver_mixin_api.py": [
        "PagesApiMixin.assert_only_listed self._pages_list",
    ],
    "apps/pages/tests/e2e/driver_mixin_browser.py": [
        "PagesBrowserMixin.assert_visitor_allowed self.last_response",
        "PagesBrowserMixin.assert_visitor_forbidden self.last_response",
    ],
    "apps/profile/tests/e2e/driver_mixin_api.py": [
        "ProfileApiMixin.assert_email_change_delivered self._email_change_requested_at",
        "ProfileApiMixin.confirm_email_change self._email_change_requested_at",
    ],
    "apps/profile/tests/e2e/driver_mixin_browser.py": [
        "ProfileBrowserMixin.assert_email_change_delivered self._email_change_requested_at",
        "ProfileBrowserMixin.assert_last_update_rejected self.last_response",
        "ProfileBrowserMixin.confirm_email_change self._email_change_requested_at",
    ],
    "apps/shared/tests/test_events.py": [
        "test_event_to_record_stringifies_uuid_payload_fields record.payload",
    ],
    "tests/e2e/drivers/browser_base.py": [
        "BrowserBase.assert_forbidden self.last_response",
        "BrowserBase.assert_not_found self.last_response",
    ],
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
    """Occurrences of ``pattern`` per file under ``roots``."""
    counts = {}
    for path, relative in _python_files(*roots):
        found = len(re.findall(pattern, path.read_text()))
        if found:
            counts[relative] = found
    return counts


def _log_calls():
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
    """The module's clock-shaped imports, bucketed, and the lines importing the clock's `now` by
    value."""
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
    """Lines reading the wall clock, through any alias, or importing the clock's `now` by value,
    which the test patch misses. Duration clocks are allowed."""
    bound, reads = _clock_bindings(tree)
    return reads + [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_wall_clock_call(node, bound)
    ]


def test_time_comes_from_the_one_clock():
    """Another wall-clock read, or the clock's `now` bound by value, escapes the test's pin."""
    strays = {
        f"{relative}:{line}"
        for path, relative in _python_files(_APPS)
        if not any(allowed in f"/{relative}" for allowed in _MAY_READ_THE_WALL_CLOCK)
        for line in _wall_clock_reads(ast.parse(path.read_text()))
    }

    assert strays == set()


def _narrowed(test: ast.expr) -> ast.expr | None:
    """The name or attribute ``assert x is not None`` or ``assert x`` narrows, else ``None``."""
    if (
        isinstance(test, ast.Compare)
        and [type(op) for op in test.ops] == [ast.IsNot]
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value is None
    ):
        test = test.left
    if isinstance(test, ast.Name) or (
        isinstance(test, ast.Attribute) and isinstance(test.value, ast.Name)
    ):
        return test
    return None


def _compensating_asserts(*roots: Path, lifecycles_only: bool = False) -> list[str]:
    """Narrowing asserts under ``roots``, by function. ``lifecycles_only`` keeps attributes and
    globals: in a test, a local checked for ``None`` is the assertion itself."""
    found = []
    for path, relative in _python_files(*roots):
        tree = ast.parse(path.read_text())
        owner = _enclosing(tree)
        module_globals = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign | ast.AnnAssign)
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert) or (narrowed := _narrowed(node.test)) is None:
                continue
            if (
                lifecycles_only
                and isinstance(narrowed, ast.Name)
                and narrowed.id not in module_globals
            ):
                continue
            found.append(
                f"{relative}::{owner.get(node.lineno, '<module>')} {ast.unparse(narrowed)}"
            )
    return sorted(found)


def test_no_compensating_assert_narrows_an_annotation():
    """(AGENTS: `| None` means optional) At zero in `apps/`."""
    in_apps = [site for site in _compensating_asserts(_APPS) if "/tests/" not in site]

    assert in_apps == []


def test_the_lifecycles_the_tests_narrow_are_the_named_ones():
    """In the harness, the same tell marks scenario lifecycles, frozen here."""
    in_tests: dict[str, list[str]] = {}
    for site in _compensating_asserts(_APPS, _ROOT / "tests", lifecycles_only=True):
        path, narrowed = site.split("::", 1)
        if "/tests/" in f"/{path}":
            in_tests.setdefault(path, []).append(narrowed)

    assert in_tests == _LIFECYCLES_THE_TESTS_NARROW


_FALLBACKS = {"{}": "or {}", "[]": "or []", "0": "or 0", "''": 'or ""'}
_SUPPRESSION = re.compile(r"#\s*(type|ty|pyright):\s*ignore")


def _enclosing(tree: ast.Module) -> dict[int, str]:
    """Line → innermost enclosing def or class, or ``<module>``."""
    owner: dict[int, str] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                name = f"{prefix}{child.name}"
                for line in range(child.lineno, (child.end_lineno or child.lineno) + 1):
                    owner[line] = name
                visit(child, f"{name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return owner


def _defensive_reads(source: str) -> list[tuple[int, str]]:
    """Lines tolerating a `None`: `or`, `typing.cast` (not SQLAlchemy's `cast`), a suppression."""
    tree = ast.parse(source)
    casts = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "typing"
        for alias in node.names
        if alias.name == "cast"
    }
    reads = [
        (node.lineno, _FALLBACKS[ast.unparse(node.values[-1])])
        for node in ast.walk(tree)
        if isinstance(node, ast.BoolOp)
        and isinstance(node.op, ast.Or)
        and ast.unparse(node.values[-1]) in _FALLBACKS
    ]
    reads += [
        (node.lineno, "cast")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in casts
    ]
    reads += [
        (number, "ignore")
        for number, line in enumerate(source.splitlines(), start=1)
        if _SUPPRESSION.search(line)
    ]
    return reads


def test_the_defensive_reads_are_the_named_ones():
    """Named per function, not counted, so a slack read cannot replace a legitimate one."""
    reads = sorted(
        f"{relative}::{_enclosing(ast.parse(source)).get(line, '<module>')} {spelling}"
        for path, relative in _python_files(_APPS)
        if "/tests/" not in relative
        for source in [path.read_text()]
        for line, spelling in _defensive_reads(source)
    )

    assert reads == _DEFENSIVE_READS


def test_no_state_wait_is_a_sleep():
    """(AGENTS: assert the settled DOM, never wait on time)"""
    assert _sites(r"networkidle|wait_for_timeout\(", _APPS, _ROOT / "tests") == {}


def test_dom_state_is_asserted_through_expect():
    """Any `is_visible()` read, not only in an `assert`: it is a snapshot either way."""
    reads = {
        f"{relative}:{node.lineno}"
        for path, relative in _python_files(_APPS, _ROOT / "tests")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Attribute) and node.attr in {"is_visible", "is_hidden"}
    }

    assert reads == set()


def _snapshot_reads_in_assertions(path: Path) -> int:
    """Snapshot DOM reads in a mixin's ``assert_*`` methods."""
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
    """Snapshot reads that no banned spelling catches, frozen."""
    reads = {
        str(mixin.relative_to(_ROOT)): found
        for mixin in sorted(_APPS.glob("*/tests/e2e/driver_mixin_browser.py"))
        if (found := _snapshot_reads_in_assertions(mixin))
    }

    assert reads == _SNAPSHOT_READS_IN_ASSERTIONS


def _called_attributes(fn: ast.AST) -> list[str]:
    return [
        node.func.attr
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]


def _mixin_methods(mixin: Path) -> tuple[dict[str, int], dict[str, set[str]]]:
    """``({method: goto calls}, {method: methods it calls})`` for a mixin, module functions
    included."""
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
    """Propagate step types to the helpers callers reach, to a fixpoint."""
    for method in calls:
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
    """``{steps.function: (step types, goto calls)}``: steps navigating without the driver."""
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
    """``{app.method: (step types reaching it, goto calls)}``, one graph for the composed driver:
    an app's steps call other apps' mixins."""
    navigations: dict[str, list[tuple[str, int]]] = defaultdict(list)
    calls: dict[str, set[str]] = defaultdict(set)
    step_modules = [_ROOT / "tests" / "e2e" / "steps_common.py"]
    for mixin in sorted(_APPS.glob("*/tests/e2e/driver_mixin_browser.py")):
        app = mixin.relative_to(_APPS).parts[0]
        gotos, callees = _mixin_methods(mixin)
        for name, count in gotos.items():
            calls[name] |= callees[name]
            if count:
                navigations[name].append((app, count))
        step_modules.append(mixin.parent / "steps.py")
    reached: dict[str, set[str]] = defaultdict(set)
    for steps in step_modules:
        for method, kinds in _steps_reaching(steps).items():
            reached[method] |= kinds
    reached = _propagated(reached, calls)
    found = {
        f"{app}.{name}": (reached[name], count)
        for name, sites in navigations.items()
        for app, count in sites
    }
    for steps in step_modules[1:]:
        app = steps.relative_to(_APPS).parts[0]
        found |= {f"{app}.{name}": reach for name, reach in _step_navigations(steps).items()}
    return found


def test_no_assertion_step_reaches_a_page_by_url():
    """A `then` that navigates asserts about a page nobody reached by the app's own way."""
    under_assertion = {
        method for method, (kinds, _) in _mixin_navigations().items() if "then" in kinds
    }

    assert under_assertion == set()


def test_every_deep_link_is_an_arrival_from_outside():
    """URL navigations are arrivals from outside the app, each with its reason."""
    navigating = set(_mixin_navigations())

    assert navigating == set(_ARRIVES_FROM_OUTSIDE)


def _is_a_request_call(node: ast.AST) -> bool:
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
    """Whether it sends a request rather than click: Playwright's request context, or a
    ``fetch(`` in an evaluated script."""
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
    """``fetch()`` is a smell too: each site says why (most prove the server refuses)."""
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
    """Frozen by file: no step to attribute them to."""
    assert _sites(r"\.goto\(", _ROOT / "tests") == _SUBSTRATE_DEEP_LINKS


def test_every_log_line_is_named_by_a_dotted_snake_case_literal():
    """A computed name escapes grep and the AST checks of the log vocabulary."""
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
    """(AGENTS: tests are sincere) GoTrue, Postgres, Storage and the mail catcher are real."""
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
    """Routers importing SQLAlchemy statements, or driving a session."""
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
    """(AGENTS: routers own HTTP and nothing else) The checkable half."""
    assert _db_touches_in_routers() == _ROUTERS_TOUCHING_THE_DB


def _calls_get_settings(node: ast.AST) -> TypeGuard[ast.Call]:
    """``get_settings(...)`` or ``live.get_settings(...)``."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "get_settings"
    return isinstance(func, ast.Attribute) and func.attr == "get_settings"


def _settings_reads_in_routers() -> set[str]:
    """``get_settings`` calls in router modules, by function, which survives edits."""
    found = set()
    for path in sorted(_APPS.glob("*/infra/*router*.py")):
        relative = str(path.relative_to(_ROOT))
        tree = ast.parse(path.read_text())
        owner = _enclosing(tree)
        for node in ast.walk(tree):
            if _calls_get_settings(node):
                found.add(f"{relative}::{owner.get(node.lineno, '<module>')}")
    return found


def test_no_router_reads_settings_by_string():
    """(AGENTS: a contract never exports a settings handle)"""
    assert _settings_reads_in_routers() == _ROUTERS_READING_SETTINGS_BY_STRING


def test_the_bypassrls_parameters_are_the_counted_ones():
    """The `python-never-reimplements-isolation` waiver's ratchet: each request on BYPASSRLS may
    redecide what RLS should."""
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
    """The `one-component-system` waiver's ratchet (it made `paper border-2` compute 1px)."""
    css = (_ROOT / "static" / "css" / "input.css").read_text()
    start, end = _component_layer_span(css)

    outside = {
        selector.group(1)
        for selector in re.finditer(r"^\s*\.([a-zA-Z][\w-]*)", css, flags=re.MULTILINE)
        if not start <= selector.start() <= end
    }

    assert outside == _OUTSIDE_THE_COMPONENT_LAYER


def test_no_template_re_spells_card_panel():
    """The `reuse-components` waiver's own example: `card-panel` is `card bg-base-100 border
    border-base-300 shadow-sm`, yet a template still spelled the shorter chain by hand. At zero."""
    spelled_out = {
        str(path.relative_to(_ROOT)): count
        for path in sorted(_APPS.rglob("*.html"))
        if (count := len(re.findall(r"card bg-base-100 border border-base-300", path.read_text())))
    }

    assert spelled_out == {}


def test_every_tab_panel_colours_its_frame_with_a_utility():
    """daisyUI's `.tab-content` sets `border-color: transparent` from the utilities layer, which
    outranks any class of our `@layer components`: a component class carrying the panel's border
    colour loses to it, and every `tabs-lift` panel renders frameless. Each panel's `class` names
    the bare `border-base-300` utility instead — a variant (`hover:`) colours nothing at rest."""
    frameless = {
        str(path.relative_to(_ROOT)): count
        for path in sorted(_APPS.rglob("*.html"))
        if (
            count := len(
                re.findall(
                    r'class="(?=[^"]*(?<![\w:-])tab-content\b)'
                    r'(?![^"]*(?<![\w:-])border-base-300\b)[^"]*"',
                    path.read_text(),
                )
            )
        )
    }

    assert frameless == {}


def test_nothing_reruns_a_failing_test():
    """Zero rerun: no rerun plugin installed or pulled in at run time, and no hook of ours takes
    over the run protocol."""
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
    """The demo apps the README lists."""
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
    """The `demo-apps-are-disposable` waiver's ratchet: modules importing a demo, which break
    when it is deleted. Templates naming a demo are not seen."""
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
# Numeric literals in ``apps/`` bound to a module constant or a parameter default, in three groups;
# only the third is a backlog (AGENTS: no magic number).

# A setting's declared default.
_DEFAULTS_OF_A_DECLARED_SETTING = {
    "apps/shared/persistence/sql_stats.py::DEFAULT_HEAVY_MS = 500",
    "apps/shared/persistence/sql_stats.py::DEFAULT_HEAVY_QUERIES = 30",
}

# Not knobs, a lever would break them: status codes, SVG dimensions, 53 weeks a year, the
# fingerprint's frame count and lengths (changing them re-groups past issues), the 9 rungs of the
# repetition ladder, an advisory lock key, ``lock_timeout_ms=0`` (Postgres's "no timeout"), the
# perf smoke's thresholds (the CI check itself).
_NOT_A_TUNING_KNOB = {
    "apps/auth/infra/admin_guard.py::_LAST_ADMIN_GUARD_LOCK_KEY = 3600360036",
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
    "apps/shared/logs/repository.py::_MAX_STATEMENT_PARAMS = 32767",
    "apps/shared/logs/repository.py::append(lock_timeout_ms=0)",
    "apps/shared/persistence/sql_stats.py::_KEPT_STATEMENTS = 5",
    "apps/shared/persistence/sql_stats.py::_MAX_STATEMENT = 300",
    "apps/tasks/domain/strip.py::_MAX_BUCKETS = 400",
    "apps/tasks/domain/strip.py::_MAX_TICKS = 8",
    "apps/tasks/domain/strip.py::_MIN_SHARE = 6.0",
    "apps/tasks/domain/strip.py::_MIN_WIDTH = 0.4",
    "scripts/smoke.py::FAIL_RATIO_MAX = 0.01",
    "scripts/smoke.py::P95_MS_MAX = 800.0",
}

# The backlog: retention windows, intervals, retry budgets, batch sizes, page lengths, deadlines,
# caps. Promoting one to a setting removes its line; widening the scan adds the knobs it finds.
_KNOBS_AWAITING_PROMOTION = {
    "apps/api_keys/infra/repository.py::_LAST_USED_GRANULARITY_SECONDS = 300",
    "apps/auth/contract/impersonation.py::IMPERSONATION_MAX_SECONDS = 3600",
    "apps/auth/infra/accounts_router.py::_PAGE_SIZE = 1000",
    "apps/auth/infra/router.py::_MFA_MAX_SECONDS = 300",
    "apps/auth/infra/router.py::_OAUTH_MAX_SECONDS = 300",
    "apps/auth/infra/user_repository.py::_PAGE_SIZE = 1000",
    "apps/console/infra/router.py::_GROWTH_DAYS = 14",
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
    "apps/shared/overview.py::RECENT_ITEMS = 3",
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
    "scripts/doctor.py::TIMEOUT_SECONDS = 5.0",
    "scripts/doctor.py::WARN_SECONDS = 0.5",
    "scripts/perf_smoke.py::_wait_ready(timeout=30.0)",
    "scripts/smoke.py::_wait_for_personal_org(timeout=10.0)",
}


def _numeric_literals(tree: ast.AST, relative: str) -> set[str]:
    """Numeric literals bound to a module-level name or a parameter default; one inside an
    expression is arithmetic."""
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
        # Equal lengths: defaults align with trailing positionals, kw_defaults hold ``None``.
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
    """A numeric ``ast.Constant``; a bool is a flag, not a number."""
    if not isinstance(node, ast.Constant):
        return False
    return isinstance(node.value, int | float) and not isinstance(node.value, bool)


def test_the_numbers_outside_the_settings_are_the_named_ones():
    """(AGENTS: no magic number) A new literal joins one of the three lists by a decision here."""
    found = {
        entry
        for path, relative in _python_files(_APPS, _ROOT / "scripts")
        if "/tests/" not in relative
        for entry in _numeric_literals(ast.parse(path.read_text()), relative)
    }

    assert found == (
        _DEFAULTS_OF_A_DECLARED_SETTING | _NOT_A_TUNING_KNOB | _KNOBS_AWAITING_PROMOTION
    )
