"""What the README asserts about this codebase, and who proves it.

The README is a promise made to whoever clones the base, and it is the one document nothing in the
suite reads. A sentence in it can therefore say anything: the code moves under it and no run ever
disagrees. This registry closes that gap by making each claim a value — its exact wording, and
either the test that holds it or the reason none does yet.

Two rules give the list its teeth, both enforced by ``tests/meta/test_claims.py``:

- **the quote is verbatim.** Reworded, the claim stops matching and the suite fails, which is the
  point: the README's head sentences are the part that drifts in silence, since nobody re-reads a
  paragraph while diffing a router.
- **the holder is a function, not a name.** ``held_by`` imports the test, so a rename moves the
  reference and a deletion breaks the import — the binding is checked before pytest even runs.

``waived`` is the honest half. A claim nobody holds is written down as such, with the reason, and
counted by ``UNHELD_TODAY``. That number is the backlog this package exists to lower.
"""

from collections.abc import Callable
from dataclasses import dataclass

from apps.shared.tests.test_bus import test_emit_refuses_an_undeclared_event
from apps.shared.tests.test_emit_durability import (
    test_a_fact_is_rolled_back_by_a_handler_that_raises,
    test_a_fact_survives_a_handler_that_returns_an_error_response,
)
from apps.shared.tests.test_limiter import (
    test_a_store_the_limiter_cannot_reach_is_a_bug,
    test_rate_limit_fails_open_when_store_is_down,
)
from apps.shared.tests.test_listener import (
    test_a_second_tick_does_not_refan_a_dispatched_fact,
    test_tick_enqueues_one_task_per_subscriber_and_marks_the_fact_dispatched,
)
from tests.e2e.drivers.test_api_isolation import test_distinct_emails_get_isolated_sessions
from tests.e2e.drivers.test_browser_isolation import test_distinct_emails_get_isolated_contexts
from tests.meta.test_capture_sites import test_a_broad_except_never_logs_without_its_traceback
from tests.meta.test_diagrams import (
    test_the_dashboard_diagram_lists_every_contributor,
    test_the_signup_diagram_draws_every_welcome_seeder,
)
from tests.meta.test_docs import (
    test_every_documented_command_exists,
    test_every_path_the_structure_tree_draws_exists,
    test_every_quality_tool_in_the_table_is_still_configured,
    test_the_stack_table_names_what_is_installed,
    test_the_test_environment_file_is_committed_and_local,
)
from tests.meta.test_emit_sites import test_the_only_way_to_record_a_fact_is_on_a_transaction
from tests.meta.test_event_vocabulary import (
    test_every_event_names_both_of_its_halves,
    test_no_event_names_an_identity_outside_the_bases_slots,
    test_the_stored_vocabulary_is_exactly_what_history_expects,
)
from tests.meta.test_lanes import (
    test_every_context_with_steps_drives_both_lanes,
    test_every_scenario_file_is_bound_exactly_once,
    test_only_the_named_scenarios_run_on_one_driver,
)
from tests.meta.test_log_thresholds import (
    test_an_error_line_carries_the_exception_that_justifies_it,
    test_nothing_is_written_below_the_two_levels,
    test_the_info_lines_are_exactly_the_surprises,
)
from tests.meta.test_log_vocabulary import (
    test_no_context_writes_a_line_under_another_apps_name,
    test_no_log_line_spells_a_business_event_kind,
)
from tests.meta.test_loop_verdicts import (
    test_a_healthy_lifespan_loop_writes_nothing,
    test_a_lifespan_loop_that_falls_over_opens_an_issue,
)
from tests.meta.test_ratchets import (
    test_dom_state_is_asserted_through_expect,
    test_every_deep_link_is_an_arrival_from_outside,
    test_every_log_line_is_named_by_a_dotted_snake_case_literal,
    test_every_request_the_driver_fires_itself_is_named,
    test_no_assertion_step_reaches_a_page_by_url,
    test_no_compensating_assert_narrows_an_annotation,
    test_no_state_wait_is_a_sleep,
    test_nothing_reruns_a_failing_test,
    test_the_defensive_reads_are_the_named_ones,
    test_time_comes_from_the_one_clock,
)
from tests.meta.test_routes import (
    test_no_org_handle_can_shadow_a_fixed_route,
    test_the_schema_describes_both_faces_of_every_page_but_the_named_ones,
)
from tests.meta.test_signin_coverage import test_every_delivered_session_is_recorded_as_a_sign_in
from tests.meta.test_surfaces import (
    test_an_issue_fact_never_names_the_user_who_tripped_it,
    test_every_context_declares_its_console_tile,
    test_every_context_declares_one_mount_entry_point,
    test_every_context_keeps_its_internals_private,
    test_no_shared_module_names_a_bounded_context,
    test_the_capture_seam_is_not_a_business_fact,
    test_the_composition_root_mounts_every_context,
    test_the_one_way_edge_out_of_auth_is_contracted,
    test_the_reference_app_fills_every_surface,
    test_the_shared_foundation_is_forbidden_from_every_context,
    test_the_timeline_writes_nothing,
)

Holder = Callable[..., object]


@dataclass(frozen=True)
class Claim:
    """A sentence the README asserts, and what stands behind it: a test, or a written waiver.

    Exactly one of the two — ``test_claims`` refuses both and neither. ``quote`` is the README's
    own words (whitespace-normalised, so it may span wrapped lines); ``held_by`` holds the test
    functions themselves, so a rename or a deletion breaks the import rather than rotting.
    """

    name: str
    quote: str
    held_by: tuple[Holder, ...] = ()
    waiver: str = ""


def held(name: str, quote: str, *by: Holder) -> Claim:
    """Bind a claim to the tests that prove it — some only in part, which the holder's own
    docstring says. Held is not the same as fully proven."""
    return Claim(name=name, quote=quote, held_by=by)


def waived(name: str, quote: str, reason: str) -> Claim:
    """Record a claim nothing proves yet. The reason says what would have to be built, not that it
    is hard — and names the ratchet where the distance is already a number."""
    return Claim(name=name, quote=quote, waiver=reason)


CLAIMS = [
    # ── Objectives ──────────────────────────────────────────────────────────────────────────────
    waived(
        "principles-are-mechanically-verifiable",
        "the principles below are mechanically verifiable",
        "this registry is that measurement, and the claim is true exactly to the degree "
        "UNHELD_TODAY is zero — nothing else can hold it without circling back here",
    ),
    waived(
        "demo-apps-are-disposable",
        "The demo apps are meant to be deleted when real work starts.",
        "no lane deletes an app and re-runs; the surface claims below are its decomposition, and "
        "holding them all is what would make a deletion safe",
    ),
    # ── Principles ──────────────────────────────────────────────────────────────────────────────
    waived(
        "apps-are-self-contained",
        "each owns its domain logic, routes, templates, tests and migrations, and can be added, "
        "disabled, or deleted without touching the others",
        "needs a per-app inventory of the five directories and a check that nothing outside them "
        "names the app",
    ),
    held(
        "boundaries-are-hard",
        "domain code never imports infrastructure; apps never import each other",
        test_the_shared_foundation_is_forbidden_from_every_context,
    ),
    held(
        "boundaries-enforced-by-import-linter",
        "These boundaries are enforced by import-linter contracts.",
        test_every_context_keeps_its_internals_private,
    ),
    held(
        "two-faces",
        "The same handler serves the JSON API and the HTML UI",
        test_the_schema_describes_both_faces_of_every_page_but_the_named_ones,
    ),
    waived(
        "integration-is-declarative",
        "An app states everything it contributes in a single mount call",
        "the AppManifest makes it readable; nothing asserts each app fills it rather than reaching "
        "around it",
    ),
    held(
        "deleting-an-app-removes-every-trace",
        "deleting an app removes every trace of it",
        test_no_shared_module_names_a_bounded_context,
    ),
    held(
        "fact-rides-a-transaction",
        "the emitter names that transaction explicitly, and there is no second way to record a "
        "fact",
        test_the_only_way_to_record_a_fact_is_on_a_transaction,
    ),
    waived(
        "only-what-happened-is-a-fact",
        "a refused attempt (a wrong password, a blocked last-owner change, a non-owner reaching an "
        "owner-only route) changed nothing, so it is a structured log line, not a fact",
        "the vocabulary test pins the kinds that exist, not the refusals that must stay out of it",
    ),
    held(
        "fact-commits-iff-the-mutation-does",
        "the fact commits iff the mutation does",
        test_a_fact_is_rolled_back_by_a_handler_that_raises,
        test_a_fact_survives_a_handler_that_returns_an_error_response,
    ),
    held(
        "emit-refuses-an-unowned-event",
        "Each app declares the events it owns, and `emit` refuses an unowned one.",
        test_emit_refuses_an_undeclared_event,
    ),
    held(
        "console-sees-every-app",
        "Each app reports server-wide stats to the SaaS console, declares its admin-tunable "
        "settings there, and can be switched on or off",
        test_every_context_declares_its_console_tile,
    ),
    waived(
        "disabled-app-keeps-its-tile",
        "a disabled app drops its routes, nav and dashboard card but keeps its console tile (and "
        "still reserves its URL slugs)",
        "needs an app mounted twice, on and off, with both route tables compared",
    ),
    waived(
        "rls-is-the-single-source-of-truth",
        "Row-level security, versioned as plain SQL migrations, is the single source of truth for "
        "who sees what.",
        "tests/rls.py exercises policies per table; nothing asserts every org-scoped table has one",
    ),
    waived(
        "python-never-reimplements-isolation",
        "Python never re-implements isolation for authenticated access.",
        "would need a walk of repositories for an org_id filter added on top of an RlsSession",
    ),
    waived(
        "only-the-journal-is-transactional",
        "Only the journal is transactional — the rest never blocks, slows or fails the action it "
        "observes.",
        "the log sink and capture seam are queue-backed by construction; no test proves a full "
        "queue leaves the request untouched",
    ),
    held(
        "scenarios-run-twice",
        "The same plain-language scenarios run twice — over real HTTP and through a real browser "
        "— against a real database.",
        test_every_scenario_file_is_bound_exactly_once,
        test_only_the_named_scenarios_run_on_one_driver,
        test_every_context_with_steps_drives_both_lanes,
    ),
    waived(
        "nothing-critical-is-mocked",
        "Nothing business-critical is mocked",
        "monkeypatch sites in the e2e lanes would have to be enumerated and named",
    ),
    held(
        "goto-is-a-smell",
        "For browser testing, goto() or fetch() should be treated as possible code smells",
        test_no_assertion_step_reaches_a_page_by_url,
        test_every_deep_link_is_an_arrival_from_outside,
        test_every_request_the_driver_fires_itself_is_named,
    ),
    waived(
        "personal-org-at-signup",
        "Every account gets a personal organization at sign-up",
        "a scenario covers the happy path; nothing ties it to this sentence",
    ),
    waived(
        "first-user-is-admin",
        "First signed-up user is admin",
        "a scenario covers it; nothing ties it to this sentence",
    ),
    held(
        "single-clock",
        "Time comes from a single clock",
        test_time_comes_from_the_one_clock,
    ),
    waived(
        "uuidv7-primary-keys",
        "every primary key is a time-ordered UUIDv7",
        "the mixin is tested in isolation; no walk asserts every mapped table uses it",
    ),
    waived(
        "one-component-system",
        "styling from one component system (Tailwind + daisyUI)",
        "needs a template scan for custom CSS classes outside the declared component layer",
    ),
    waived(
        "invariants-are-types",
        "A constraint the domain must uphold is expressed as a constrained type",
        "a judgement call per constraint — the closest mechanical proxy is the claim below",
    ),
    held(
        "none-means-optional",
        "A compensating `assert x is not None`, a defensive `or {}` at every read, or a "
        "suppression added to tolerate either, is the sign the annotation is wider than the truth.",
        test_no_compensating_assert_narrows_an_annotation,
        test_the_defensive_reads_are_the_named_ones,
    ),
    # ── Stack and quality tools ─────────────────────────────────────────────────────────────────
    held(
        "stack-table-is-current",
        "| **Web framework** | FastAPI",
        test_the_stack_table_names_what_is_installed,
    ),
    held(
        "quality-tools-are-installed",
        "| **import-linter** | Architecture boundaries between apps (contracts in "
        "`pyproject.toml`) |",
        test_every_quality_tool_in_the_table_is_still_configured,
    ),
    # ── Architecture ────────────────────────────────────────────────────────────────────────────
    waived(
        "routers-own-http",
        "Routers own HTTP and nothing else — parsing, serialization, status codes; no business "
        "logic, no direct DB access.",
        "a router issuing its own select would pass every gate the repo has",
    ),
    waived(
        "three-audiences",
        "Every business route answers three audiences from one handler",
        "the JSON and HTML faces are held (see two-faces); the third is not — nothing asks "
        "which routes actually have an HTMX fragment",
    ),
    waived(
        "tests-live-with-their-context",
        "Templates, tests, and BDD steps live with their context",
        "a layout convention, checkable per app from the directory tree",
    ),
    # ── Integration ─────────────────────────────────────────────────────────────────────────────
    held(
        "single-mount-entry",
        "Each bounded context exposes a single `mount(host)` entry point in its "
        "`contract/integration.py`",
        test_every_context_declares_one_mount_entry_point,
        test_the_composition_root_mounts_every_context,
    ),
    held(
        "catch-alls-sort-last",
        "catch-all routes (e.g. the org `/{slug}`) sort last so a fixed route is never shadowed",
        test_no_org_handle_can_shadow_a_fixed_route,
    ),
    held(
        "surfaces-are-registered",
        "Because every surface is registered rather than hardcoded",
        test_no_shared_module_names_a_bounded_context,
    ),
    waived(
        "contract-never-exports-a-settings-handle",
        "A contract never exports a settings handle",
        "an AST check over each contract package's public names",
    ),
    waived(
        "no-magic-strings-in-collaboration",
        "Both key handlers by the Python type they carry, so there are no magic strings and no "
        "shared imports.",
        "the registries are typed; nothing forbids a string-keyed sibling being added",
    ),
    held(
        "signing-in-is-one-fact",
        "`set_auth_cookies` is the single place a session is delivered, and a test over its call "
        "sites holds the rule: each one records a sign-in",
        test_every_delivered_session_is_recorded_as_a_sign_in,
    ),
    held(
        "capture-is-not-on-the-bus",
        "Technical error capture is *not* on the bus",
        test_the_capture_seam_is_not_a_business_fact,
    ),
    held(
        "signup-chain",
        "→ files: seeds welcome.txt → todo: seeds 3 welcome todos",
        test_the_signup_diagram_draws_every_welcome_seeder,
    ),
    held(
        "dashboard-collects-five-overviews",
        "← files, learning, todo, calendar, pages each return an Overview (icon, title, counts, "
        "recent items)",
        test_the_dashboard_diagram_lists_every_contributor,
    ),
    held(
        "auth-never-imports-organizations",
        "an import-linter contract enforces the one-way edges, e.g. auth never imports "
        "organizations",
        test_the_one_way_edge_out_of_auth_is_contracted,
    ),
    # ── Observability ───────────────────────────────────────────────────────────────────────────
    held(
        "kind-is-derived",
        "its `kind` (`todo.ticked`, `organizations.renamed`) derived from an app prefix and a "
        "verb, never hand-written",
        test_the_stored_vocabulary_is_exactly_what_history_expects,
        test_every_event_names_both_of_its_halves,
    ),
    held(
        "entity-id-correlates",
        "a business event's `entity_id` correlates entities by their stable pk, never a "
        "renameable handle",
        test_no_event_names_an_identity_outside_the_bases_slots,
    ),
    held(
        "a-fact-is-said-once",
        "`emit` logs nothing of its own, so an action shows up once, not twice.",
        test_no_log_line_spells_a_business_event_kind,
    ),
    held(
        "a-line-carries-its-app",
        "Every line carries its logger, and that name is the `app` axis the Timeline reads.",
        test_no_context_writes_a_line_under_another_apps_name,
    ),
    held(
        "a-broad-except-carries-its-stack",
        "A broad `except Exception` that logs carries its `exc_info`, so the stack survives even "
        "where the failure is handled rather than tracked (an AST test holds the rule).",
        test_a_broad_except_never_logs_without_its_traceback,
    ),
    held(
        "no-debug-tier",
        "there is no `debug` tier",
        test_nothing_is_written_below_the_two_levels,
    ),
    held(
        "info-is-a-surprise",
        "`info` is **a point of surprise** — never the happy path",
        test_the_info_lines_are_exactly_the_surprises,
    ),
    held(
        "a-bare-error-is-not-the-seam",
        "A bare `log.error` is deliberately not the seam",
        test_an_error_line_carries_the_exception_that_justifies_it,
    ),
    held(
        "a-loop-that-falls-over-opens-an-issue",
        "falling over opens one issue, the ticks after it warn with how many, coming back says "
        "what the outage cost.",
        test_a_lifespan_loop_that_falls_over_opens_an_issue,
    ),
    held(
        "silence-at-rest",
        "A healthy server at rest writes nothing at all, which is what makes its silence readable",
        test_a_healthy_lifespan_loop_writes_nothing,
    ),
    held(
        "log-names-are-dotted-snake-case",
        "dotted `snake_case` names with kwargs, never f-strings or `print`",
        test_every_log_line_is_named_by_a_dotted_snake_case_literal,
    ),
    waived(
        "request-finished-once-per-request",
        "Every served request leaves one `request.finished` line — including one whose handler "
        "raised",
        "needs a request driven end to end with the sink captured",
    ),
    held(
        "timeline-writes-nothing",
        "`apps/timeline` writes nothing",
        test_the_timeline_writes_nothing,
    ),
    held(
        "issues-name-the-request-never-its-user",
        "naming the request that tripped them, never its user",
        test_an_issue_fact_never_names_the_user_who_tripped_it,
    ),
    waived(
        "one-dependency-verdict",
        "One verdict (`apps/shared/logs/dependency.py`) for GoTrue, Postgres and Storage alike",
        "the verdict is unit-tested; nothing stops a second one being written next to it",
    ),
    held(
        "metrics-owns-the-counter",
        "the app subscribes at mount and shared never names it",
        test_no_shared_module_names_a_bounded_context,
    ),
    # ── Conventions ─────────────────────────────────────────────────────────────────────────────
    waived(
        "three-session-dependencies",
        "Three DB session dependencies: `RlsSession` (default — RLS enforced), "
        "`get_user_session` (raw), `AdminSession` (BYPASSRLS",
        "a fourth would be a real decision and would announce itself nowhere",
    ),
    waived(
        "enqueue-is-outbox",
        "`enqueue()` writes through the caller's session, so a task exists iff the business "
        "transaction commits (outbox semantics)",
        "the queue is well tested; this exact sentence — the rollback case — is not",
    ),
    held(
        "the-limiter-fails-open",
        "The limiter fails open: a store it cannot reach lets the request through, because rate "
        "limiting must never be what takes an endpoint down",
        test_rate_limit_fails_open_when_store_is_down,
        test_a_store_the_limiter_cannot_reach_is_a_bug,
    ),
    held(
        "a-fact-is-fanned-out-once",
        "It claims what it dispatches in the transaction that stamps it",
        test_tick_enqueues_one_task_per_subscriber_and_marks_the_fact_dispatched,
        test_a_second_tick_does_not_refan_a_dispatched_fact,
    ),
    waived(
        "csrf-without-tokens",
        "Cross-site mutations are rejected by a `Sec-Fetch-Site` middleware (CSRF protection "
        "without tokens)",
        "the middleware is unit-tested; nothing asserts it is still mounted on the real app",
    ),
    waived(
        "fragments-are-standalone-markup",
        "Fragments are standalone valid markup (they're swapped into the live DOM).",
        "needs each _*.html rendered and parsed",
    ),
    held(
        "never-call-datetime-now",
        "`clock.now()` is the single source of time. Never call `datetime.now()`.",
        test_time_comes_from_the_one_clock,
    ),
    waived(
        "tokens-stay-uuidv4",
        "Security tokens are the deliberate exception — they stay random **UUIDv4**",
        "the exception has no list, so it cannot be checked in either direction",
    ),
    held(
        "every-actor-isolated-session",
        "Every actor in a scenario gets an isolated session",
        test_distinct_emails_get_isolated_sessions,
        test_distinct_emails_get_isolated_contexts,
    ),
    held(
        "browser-navigates-like-a-human",
        "The browser driver navigates like a human: entry point, then links and forms — no deep "
        "URLs.",
        test_no_assertion_step_reaches_a_page_by_url,
        test_every_deep_link_is_an_arrival_from_outside,
    ),
    held(
        "expect-not-is-visible",
        "Assert DOM state with `expect(...)` (auto-retries to the settled state), never `assert "
        "locator.is_visible()`",
        test_dom_state_is_asserted_through_expect,
    ),
    held(
        "no-networkidle-no-timeout",
        "and `wait_for_timeout(ms)` are banned",
        test_no_state_wait_is_a_sleep,
    ),
    held(
        "reruns-are-opt-in",
        "Reruns are opt-in and justified per named suite; everything else is strict, zero rerun.",
        test_nothing_reruns_a_failing_test,
    ),
    # ── Structure, client, setup ────────────────────────────────────────────────────────────────
    held(
        "structure-tree-is-real",
        "├── features/              # BDD Gherkin scenarios (plain text, no code)",
        test_every_path_the_structure_tree_draws_exists,
    ),
    waived(
        "one-composition-root",
        "One top-level module forms the composition root — the only place allowed to know several "
        "contexts at once: `main.py`.",
        "import-linter forbids the edges; nothing names main.py as the only exception",
    ),
    waived(
        "client-is-generated",
        "It is generated\ncode: never edit it, re-run `make client-gen` after changing routes or "
        "DTOs.",
        "a drift shows up as a failing perf smoke, which is a slow and indirect way to say it",
    ),
    held(
        "env-test-is-committed",
        "`.env.test` is committed and uses `localhost`.",
        test_the_test_environment_file_is_committed_and_local,
    ),
    held(
        "documented-commands-exist",
        "make finalize     # js-build + fix + test (run before committing)",
        test_every_documented_command_exists,
    ),
    # ── Demo apps ───────────────────────────────────────────────────────────────────────────────
    held(
        "todo-is-the-full-pattern-reference",
        "trivial CRUD wired to every surface — nav, dashboard overview, console overview, "
        "settings, feature switch, seeding, both test drivers.",
        test_the_reference_app_fills_every_surface,
    ),
]

# Claims nothing holds yet. It only goes down: waiving a new one is a decision, and this line is
# where the decision is recorded.
UNHELD_TODAY = 29
