"""What AGENTS.md and the README assert about this codebase, and who proves it.

AGENTS.md is the rule every agent works under, and the README a promise made to whoever clones the
base; nothing else in the suite reads them. A sentence in them can therefore say anything: the
code moves under it and no run ever disagrees. This registry closes that gap by making each claim a
value — its exact wording, and either the test that holds it or the reason none does yet.

Two rules give the list its teeth, both enforced by ``tests/meta/test_claims.py``:

- **the quote is verbatim.** Reworded, the claim stops matching and the suite fails, which is the
  point: the head sentences are the part that drifts in silence, since nobody re-reads a
  paragraph while diffing a router.
- **the holder is a function, not a name.** ``held_by`` imports the test, so a rename moves the
  reference and a deletion breaks the import — the binding is checked before pytest even runs.

``waived`` is the honest half. A claim nobody holds is written down as such, with the reason, and
counted by ``UNHELD_TODAY``. That number is the backlog this package exists to lower.
"""

from dataclasses import dataclass
from types import FunctionType

from apps.auth.tests.test_auth_dependencies import (
    test_get_rls_session_gives_an_anonymous_caller_a_context_with_no_identity,
)
from apps.auth.tests.test_signin_vocabulary import (
    test_a_sign_in_records_that_a_second_factor_was_cleared,
)
from apps.console.tests.e2e.test_admins_scenarios import (
    test_an_admin_adds_another_admin_by_email,
    test_the_first_registered_user_becomes_a_server_admin,
)
from apps.health.tests.test_health import test_a_readiness_probe_that_starts_failing_says_why
from apps.issues.tests.test_capture import (
    test_the_fact_that_opens_an_issue_points_back_at_the_request,
)
from apps.issues.tests.test_service import (
    test_fingerprint_distinguishes_exception_types,
    test_fingerprint_ignores_the_variable_message,
)
from apps.metrics.tests.test_accumulator import test_render_prometheus_exposes_cumulative_histogram
from apps.metrics.tests.test_flush_and_rollup import (
    test_rollup_downsamples_old_minute_rows_then_purge_applies_retention,
)
from apps.organizations.tests.e2e.test_scenarios import (
    test_a_new_user_gets_a_personal_organisation_on_registration,
)
from apps.shared.tests.test_bus import test_emit_refuses_an_undeclared_event
from apps.shared.tests.test_capture import test_the_drain_reports_the_captures_the_queue_had_to_shed
from apps.shared.tests.test_email import test_enqueue_email_outboxes_through_the_callers_session
from apps.shared.tests.test_emit_durability import (
    test_a_fact_is_rolled_back_by_a_handler_that_raises,
    test_a_fact_survives_a_handler_that_returns_an_error_response,
)
from apps.shared.tests.test_form_as_json import (
    test_a_form_reaches_the_handler_as_its_declared_body,
    test_a_multipart_upload_is_left_alone,
)
from apps.shared.tests.test_host_fullpage import (
    test_register_fullpage_provider_rejects_a_duplicate_name,
    test_register_fullpage_provider_rejects_a_key_colliding_with_the_seeded_context,
    test_register_fullpage_provider_rejects_a_key_collision_across_two_names,
)
from apps.shared.tests.test_limiter import (
    test_a_store_that_never_answers_fails_open_within_its_timeout,
    test_a_store_the_limiter_cannot_reach_is_a_bug,
    test_rate_limit_fails_open_when_store_is_down,
)
from apps.shared.tests.test_listener import (
    test_a_second_tick_does_not_refan_a_dispatched_fact,
    test_tick_enqueues_one_task_per_subscriber_and_marks_the_fact_dispatched,
    test_tick_runs_spread_handlers_per_instance_off_the_trail,
)
from apps.shared.tests.test_log_chain import test_only_a_library_line_is_held_to_the_warning_floor
from apps.shared.tests.test_log_repository import (
    test_append_writes_the_whole_batch_as_one_statement,
    test_retention_drops_a_whole_day_as_one_partition,
)
from apps.shared.tests.test_log_sink import (
    test_a_batch_the_store_refuses_lands_in_the_day_file,
    test_a_store_that_refuses_is_announced_once,
    test_processor_enqueues_without_writing,
    test_the_drain_reports_the_lines_the_queue_had_to_shed,
)
from apps.shared.tests.test_queue import (
    test_a_task_parked_for_good_is_captured_as_a_bug,
    test_a_task_rolls_back_with_the_transaction_that_enqueued_it,
    test_recurring_task_reenqueues_next_run,
    test_worker_runs_enqueued_task,
)
from apps.shared.tests.test_request_logging import (
    test_a_failing_liveness_probe_is_traced_at_error,
    test_a_failing_readiness_probe_is_traced_at_error,
    test_a_full_sink_and_a_full_capture_queue_leave_the_request_untouched,
    test_a_healthy_liveness_probe_leaves_no_line,
    test_a_healthy_readiness_probe_leaves_no_line,
    test_a_raising_observer_never_replaces_the_handlers_own_exception,
)
from apps.shared.tests.test_uuid7 import test_uuid7_is_time_ordered_and_versioned
from apps.timeline.tests.test_pivots import test_a_row_correlates_by_the_request_it_names
from apps.timeline.tests.test_sort_honesty import (
    test_a_column_sort_says_it_only_orders_the_page,
    test_ascending_time_says_it_only_orders_the_page,
    test_the_default_sort_claims_nothing,
)
from tests.e2e.drivers.test_api_isolation import test_distinct_emails_get_isolated_sessions
from tests.e2e.drivers.test_api_rls import (
    test_the_rls_session_runs_as_the_app_role_and_the_admin_one_does_not,
)
from tests.e2e.drivers.test_browser_isolation import test_distinct_emails_get_isolated_contexts
from tests.e2e.drivers.test_conformance import (
    test_an_answer_straying_from_its_schema_is_named_by_its_operation,
)
from tests.meta.test_capture_sites import test_a_broad_except_never_logs_without_its_traceback
from tests.meta.test_conventions import (
    test_every_mapped_primary_key_is_a_time_ordered_uuid7,
    test_no_fragment_response_starts_inside_a_table,
    test_templates_tests_and_steps_live_with_their_context,
    test_the_session_dependencies_are_exactly_the_three_named,
    test_the_uuid4_exception_is_exactly_the_token_columns,
)
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
from tests.meta.test_emit_sites import (
    test_every_link_of_the_journal_writer_has_its_one_caller,
    test_the_only_way_to_record_a_fact_is_on_a_transaction,
)
from tests.meta.test_event_vocabulary import (
    test_an_org_scoped_event_declares_its_org_as_required,
    test_every_event_names_both_of_its_halves,
    test_no_event_names_an_identity_outside_the_bases_slots,
    test_only_what_happened_is_a_fact,
    test_the_signup_trigger_spells_the_fact_its_class_derives,
    test_the_stored_vocabulary_is_exactly_what_history_expects,
)
from tests.meta.test_lanes import (
    test_every_context_with_steps_drives_both_lanes,
    test_every_scenario_file_is_bound_exactly_once,
    test_only_the_named_scenarios_run_on_one_driver,
    test_the_browser_lane_collects_every_scenario_module,
)
from tests.meta.test_log_thresholds import (
    test_an_error_line_carries_the_exception_that_justifies_it,
    test_nothing_is_written_below_the_two_levels,
    test_the_info_lines_are_exactly_the_surprises,
)
from tests.meta.test_log_vocabulary import (
    test_no_context_writes_a_line_under_another_apps_name,
    test_no_log_line_spells_a_business_event_kind,
    test_the_emit_path_says_nothing_of_its_own,
)
from tests.meta.test_loop_verdicts import (
    test_a_healthy_lifespan_loop_writes_nothing,
    test_a_lifespan_loop_that_falls_over_opens_an_issue,
    test_a_loop_that_comes_back_says_what_the_outage_cost,
)
from tests.meta.test_middleware import (
    test_a_cross_site_mutation_is_rejected_by_the_assembled_app,
    test_a_request_whose_handler_raised_still_leaves_its_finished_line,
    test_a_served_request_leaves_exactly_one_finished_line,
)
from tests.meta.test_ratchets import (
    test_dom_state_is_asserted_through_expect,
    test_every_deep_link_is_an_arrival_from_outside,
    test_every_log_line_is_named_by_a_dotted_snake_case_literal,
    test_every_request_the_driver_fires_itself_is_named,
    test_no_assertion_step_reaches_a_page_by_url,
    test_no_compensating_assert_narrows_an_annotation,
    test_no_router_reaches_the_database_itself,
    test_no_router_reads_settings_by_string,
    test_no_state_wait_is_a_sleep,
    test_nothing_reruns_a_failing_test,
    test_the_defensive_reads_are_the_named_ones,
    test_the_e2e_doubles_are_the_named_ones,
    test_the_lifecycles_the_tests_narrow_are_the_named_ones,
    test_the_numbers_outside_the_settings_are_the_named_ones,
    test_the_snapshot_reads_in_assertions_are_the_named_ones,
    test_time_comes_from_the_one_clock,
)
from tests.meta.test_routes import (
    test_every_fixed_route_wins_its_first_match,
    test_every_json_face_declares_its_schema,
    test_every_mutation_declares_the_body_it_reads,
    test_every_operation_has_its_own_id,
    test_no_org_handle_can_shadow_a_fixed_route,
    test_the_schema_describes_both_faces_of_every_page_but_the_named_ones,
)
from tests.meta.test_schema_parity import test_every_closed_set_column_is_a_python_enum
from tests.meta.test_signin_coverage import test_every_delivered_session_is_recorded_as_a_sign_in
from tests.meta.test_surfaces import (
    test_a_disabled_app_drops_everything_but_its_console_tile,
    test_an_issue_fact_never_names_the_user_who_tripped_it,
    test_every_context_declares_its_console_tile,
    test_every_context_declares_one_mount_entry_point,
    test_every_context_keeps_its_internals_private,
    test_every_icon_a_surface_declares_has_a_glyph_to_render,
    test_no_contract_exports_a_settings_handle,
    test_no_shared_module_names_a_bounded_context,
    test_no_template_spells_an_icon_as_a_literal_glyph,
    test_nothing_outside_a_demo_names_it,
    test_the_capture_seam_is_not_a_business_fact,
    test_the_collaboration_registries_are_keyed_by_type_alone,
    test_the_composition_root_is_the_only_module_that_mounts,
    test_the_composition_root_mounts_every_context,
    test_the_one_way_edge_out_of_auth_is_contracted,
    test_the_reference_app_fills_every_surface,
    test_the_shared_foundation_is_forbidden_from_every_context,
    test_the_timeline_writes_nothing,
)
from tests.test_authorization_rules import (
    test_the_database_gives_each_rule_its_verdict,
    test_the_route_gives_each_rule_its_verdict,
)
from tests.test_db_privileges import (
    test_every_function_a_policy_calls_is_a_declared_guard,
    test_every_public_table_enforces_row_level_security,
    test_every_table_an_authorization_helper_guards_has_its_rules,
)

# A plain function, not any callable: the registry reads its name and module.
Holder = FunctionType


@dataclass(frozen=True)
class Claim:
    """A sentence AGENTS.md or the README asserts, and what stands behind it: a test, or a written
    waiver.

    Exactly one of the two — ``test_claims`` refuses both and neither. ``quote`` is the document's
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
        "two ratchets measure the distance: test_the_modules_outside_a_demo_that_import_it_are_"
        "the_named_ones freezes the imports, test_nothing_outside_a_demo_names_it the strings — "
        "the claim holds when both lists are empty",
    ),
    # ── Principles ──────────────────────────────────────────────────────────────────────────────
    waived(
        "apps-are-self-contained",
        "each owns its domain logic, routes, templates, tests and migrations, and can be added, "
        "disabled, or deleted without touching the others",
        "test_the_modules_outside_a_demo_that_import_it_are_the_named_ones inventories what "
        "outside a demo imports it, test_nothing_outside_a_demo_names_it what names one by "
        "string; both must be empty for the sentence to hold, and neither covers the foundation "
        "apps",
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
        test_every_mutation_declares_the_body_it_reads,
        test_an_answer_straying_from_its_schema_is_named_by_its_operation,
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
        test_nothing_outside_a_demo_names_it,
    ),
    held(
        "fact-rides-a-transaction",
        "the emitter names that transaction explicitly, and there is no second way to record a "
        "fact",
        test_the_only_way_to_record_a_fact_is_on_a_transaction,
        test_every_link_of_the_journal_writer_has_its_one_caller,
    ),
    held(
        "only-what-happened-is-a-fact",
        "a refused attempt (a wrong password, a blocked last-owner change, a non-owner reaching an "
        "owner-only route) changed nothing, so it is a structured log line, not a fact",
        test_only_what_happened_is_a_fact,
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
    held(
        "disabled-app-keeps-its-tile",
        "a disabled app drops its routes, nav and dashboard card but keeps its console tile (and "
        "still reserves its URL slugs)",
        test_a_disabled_app_drops_everything_but_its_console_tile,
    ),
    held(
        "rls-is-the-single-source-of-truth",
        "Row-level security, versioned as plain SQL migrations, is the single source of truth for "
        "who sees what.",
        test_every_public_table_enforces_row_level_security,
        test_the_rls_session_runs_as_the_app_role_and_the_admin_one_does_not,
    ),
    held(
        "authorization-rules-at-both-doors",
        "Every authorization rule is stated once and checked at both the database and the route.",
        test_every_function_a_policy_calls_is_a_declared_guard,
        test_every_table_an_authorization_helper_guards_has_its_rules,
        test_the_database_gives_each_rule_its_verdict,
        test_the_route_gives_each_rule_its_verdict,
    ),
    waived(
        "python-never-reimplements-isolation",
        "Python never re-implements isolation for authenticated access.",
        "test_the_bypassrls_parameters_are_the_counted_ones counts the surface where Python may "
        "be re-deciding what RLS should; holding the sentence needs the pages and avatar reads "
        "moved onto RLS policies first (ROADMAP)",
    ),
    held(
        "only-the-journal-is-transactional",
        "Only the journal is transactional — the rest never blocks, slows or fails the action it "
        "observes.",
        test_a_full_sink_and_a_full_capture_queue_leave_the_request_untouched,
        test_the_drain_reports_the_lines_the_queue_had_to_shed,
        test_the_drain_reports_the_captures_the_queue_had_to_shed,
        test_a_raising_observer_never_replaces_the_handlers_own_exception,
    ),
    held(
        "scenarios-run-twice",
        "The same plain-language scenarios run twice — over real HTTP and through a real browser "
        "— against a real database.",
        test_every_scenario_file_is_bound_exactly_once,
        test_only_the_named_scenarios_run_on_one_driver,
        test_every_context_with_steps_drives_both_lanes,
        test_the_browser_lane_collects_every_scenario_module,
    ),
    held(
        "nothing-critical-is-mocked",
        "Nothing business-critical is mocked",
        test_the_e2e_doubles_are_the_named_ones,
    ),
    held(
        "goto-is-a-smell",
        "For browser testing, goto() or fetch() should be treated as possible code smells",
        test_no_assertion_step_reaches_a_page_by_url,
        test_every_deep_link_is_an_arrival_from_outside,
        test_every_request_the_driver_fires_itself_is_named,
    ),
    held(
        "personal-org-at-signup",
        "Every account gets a personal organization at sign-up",
        test_a_new_user_gets_a_personal_organisation_on_registration,
    ),
    held(
        "first-user-is-admin",
        "Whoever signs up while the server has no admin becomes one",
        test_the_first_registered_user_becomes_a_server_admin,
    ),
    held(
        "single-clock",
        "Time comes from a single clock",
        test_time_comes_from_the_one_clock,
    ),
    held(
        "uuidv7-primary-keys",
        "every primary key is a time-ordered UUIDv7",
        test_every_mapped_primary_key_is_a_time_ordered_uuid7,
    ),
    waived(
        "one-component-system",
        "styling from one component system (Tailwind + daisyUI)",
        "test_the_classes_outside_the_component_layer_are_the_named_ones freezes the 36 plain-CSS "
        "classes that today beat the layer in the cascade; the claim holds when that set is empty",
    ),
    held(
        "invariants-are-types",
        "A constraint the domain must uphold is expressed as a constrained type",
        test_every_closed_set_column_is_a_python_enum,
        test_an_org_scoped_event_declares_its_org_as_required,
    ),
    held(
        "no-magic-number",
        "A number that tunes behaviour — a batch size, a poll interval, a retention window, a "
        "retry budget, a page length — is a setting, not a literal",
        test_the_numbers_outside_the_settings_are_the_named_ones,
    ),
    held(
        "none-means-optional",
        "A compensating `assert x is not None`, a defensive `or {}` at every read, or a "
        "suppression added to tolerate either, is the sign the annotation is wider than the truth.",
        test_no_compensating_assert_narrows_an_annotation,
        test_the_defensive_reads_are_the_named_ones,
        test_the_lifecycles_the_tests_narrow_are_the_named_ones,
    ),
    held(
        "only-contract-and-bus-between-apps",
        "The only inter-app surfaces are each app's public contract and the event bus.",
        test_every_context_keeps_its_internals_private,
    ),
    waived(
        "no-separate-frontend",
        "One implementation buys a documented REST API _and_ a server-rendered, dynamic front "
        "end, with no separate frontend project and no JS build step.",
        "the two faces are held (two-faces); nothing asserts the absence of a JS bundle or a "
        "second project — a package.json script building one would pass",
    ),
    waived(
        "reactions-run-after-commit",
        "a reaction that finds its subject already gone is a clean no-op, never a compensation.",
        "delivery after commit is held by the listener tests; the org-seeding no-op is held test "
        "by test (test_seed_org_welcome_no_ops_when_the_resolved_owner_is_gone, the files "
        "seeder's own test_a_seeder_whose_owner_is_already_gone_is_a_clean_no_op), but nothing "
        "asserts the rule once for every reaction the bus delivers",
    ),
    held(
        "emitter-never-names-subscribers",
        "The emitter never names its subscribers.",
        test_the_collaboration_registries_are_keyed_by_type_alone,
        test_the_shared_foundation_is_forbidden_from_every_context,
    ),
    waived(
        "console-ships-the-operational-screens",
        "Beyond per-app stats, the console ships the operational screens",
        "each screen has its scenarios; nothing checks the sentence's list against the console's "
        "own navigation, so a screen dropped from one is not missed by the other",
    ),
    held(
        "policy-helpers-isolation-and-authorization",
        "A policy calls two kinds of helper: *isolation* (which org a row belongs to), held by "
        "SQL alone, and *authorization* (which role may act on it), which the route repeats — "
        "exactly, never stricter — so a refusal reads as a clean 403.",
        test_every_function_a_policy_calls_is_a_declared_guard,
        test_the_database_gives_each_rule_its_verdict,
        test_the_route_gives_each_rule_its_verdict,
    ),
    waived(
        "sql-holds-the-invariants",
        "SQL also holds the invariants, what must never become false whoever writes; decisions "
        "and derived values stay in Python.",
        "no inventory says which rules are invariants and which are decisions, so neither side "
        "of the line can be checked — a trigger computing a derived value would pass",
    ),
    waived(
        "three-records-correlated",
        "the console's Timeline reads all three and correlates them per user, org, request and "
        "entity.",
        "each correlation key has scenarios; nothing checks that every record kind carries every "
        "key it can, so a source that stops binding one only drops out of a filter",
    ),
    held(
        "members-read-owners-write",
        "Members read, owners write.",
        test_the_database_gives_each_rule_its_verdict,
        test_the_route_gives_each_rule_its_verdict,
    ),
    held(
        "admins-promote-admins",
        "They can then promote any other user as admin.",
        test_an_admin_adds_another_admin_by_email,
    ),
    held(
        "a-literal-is-a-release-knob",
        "A value inlined in a signature or frozen in a module constant is a knob only a new "
        "release can turn.",
        test_the_numbers_outside_the_settings_are_the_named_ones,
    ),
    held(
        "three-kinds-of-number-are-not-knobs",
        "Three kinds of number are not that",
        test_the_numbers_outside_the_settings_are_the_named_ones,
    ),
    held(
        "none-is-not-unknown",
        "Not _unknown_ — if no writer can produce a `None`, the annotation is slack",
        test_the_defensive_reads_are_the_named_ones,
    ),
    held(
        "none-is-not-not-yet",
        "Not _not yet_ — a value bound after construction is a lifecycle",
        test_no_compensating_assert_narrows_an_annotation,
        test_the_lifecycles_the_tests_narrow_are_the_named_ones,
    ),
    waived(
        "not-null-down-to-the-schema",
        "a column is `not null` wherever null is unreachable.",
        "nothing compares a nullable column with its writers; the `jsonb not null` payloads the "
        "`| None` ratchet leaned on were found by hand",
    ),
    waived(
        "markup-is-semantic-and-accessible",
        "markup is semantic and accessible",
        "a clause inside the single-clock sentence, so the sentence binding cannot see it; no "
        "accessibility audit runs over the rendered pages",
    ),
    # ── AGENTS Architecture ───────────────────────────────────────────────────────────────
    held(
        "each-context-splits-domain-from-infra",
        "Organized by **bounded context**, each split into `domain/`",
        test_the_shared_foundation_is_forbidden_from_every_context,
    ),
    waived(
        "architecture-shared-homes",
        "Shared layout sits in `apps/shared/templates/`, Gherkin `.feature` files in "
        "`features/`, and shared E2E drivers in `tests/e2e/drivers/`.",
        "test_templates_tests_and_steps_live_with_their_context holds the per-context half; "
        "nothing checks the shared homes",
    ),
    # ── AGENTS Integration ────────────────────────────────────────────────────────────────
    held(
        "settings-dependency-per-request",
        "Handlers declare the app's `TodoSettings` dependency",
        test_no_contract_exports_a_settings_handle,
        test_no_router_reads_settings_by_string,
    ),
    waived(
        "non-request-settings-read",
        'Non-request code uses `get_settings("todo")`, plus `.for_org(session, org_id)` when '
        "an org is in hand.",
        "no inventory of the non-request call sites; a request handler calling get_settings "
        "would pass",
    ),
    waived(
        "push-and-pull-are-two-objects",
        "Push (a fact happened) and pull (who contributes to this?) are different animals, so "
        "they are different objects",
        "both registries are held keyed by type (no-magic-strings-in-collaboration); nothing "
        "asserts neither grows the other's verbs",
    ),
    held(
        "emit-persists-on-the-callers-session",
        "`emit(event, session)` **persists** the `BusinessEvent` to the journal on the session "
        "the caller names",
        test_a_fact_is_rolled_back_by_a_handler_that_raises,
        test_a_fact_survives_a_handler_that_returns_an_error_response,
    ),
    held(
        "emit-session-is-required",
        "The session is a required argument: durability is stated at the call site",
        test_the_only_way_to_record_a_fact_is_on_a_transaction,
    ),
    held(
        "emit-refuses-an-undeclared-event",
        "It refuses an event no app declared",
        test_emit_refuses_an_undeclared_event,
    ),
    held(
        "reactions-delivered-off-the-journal",
        "are delivered by the event listener off the persisted journal after commit",
        test_tick_enqueues_one_task_per_subscriber_and_marks_the_fact_dispatched,
        test_tick_runs_spread_handlers_per_instance_off_the_trail,
    ),
    waived(
        "reactions-treat-facts-as-history",
        "Reactions treat the fact as immutable history",
        "the rule of reactions-run-after-commit, with its gap: no test makes a subject "
        "disappear before its reaction runs",
    ),
    waived(
        "the-bus-decouples-twice",
        "The bus decouples twice",
        "explanatory: its space half is held by emitter-never-names-subscribers and its time "
        "half by the listener tests; nothing binds this sentence itself",
    ),
    waived(
        "self-subscription-needs-the-time-half",
        "an app reacting to itself is legitimate exactly when it needs the second",
        "nothing inventories the self-subscriptions, so one that could run inline would pass",
    ),
    waived(
        "self-subscription-otherwise-a-call",
        "Otherwise it is a function call written the long way round.",
        "the same missing inventory of self-subscriptions",
    ),
    held(
        "a-sign-in-is-one-event",
        "is the same event — `auth.signed_in` —",
        test_a_sign_in_records_that_a_second_factor_was_cleared,
    ),
    held(
        "a-sign-in-is-recorded-at-handover",
        "It is recorded at the moment the session is handed over, never before",
        test_every_delivered_session_is_recorded_as_a_sign_in,
    ),
    waived(
        "contribs-declared-at-mount",
        "A registry of contribution providers (an extension point), declared at mount and read "
        "synchronously on the request path",
        "nothing checks that providers are registered at mount only",
    ),
    waived(
        "signup-off-the-critical-path",
        "never on the signup's critical path",
        "the seeders are held (signup-chain); nothing asserts the signup answers before its "
        "reactions run",
    ),
    waived(
        "import-downward",
        "**Direct contract import** when the call points *down* to a foundation every feature "
        "may depend on",
        "only auth's one-way edge is contracted (auth-never-imports-organizations); "
        "organizations and console have no contract of their own",
    ),
    waived(
        "event-upward",
        "you *want* the coupling explicit",
        "the same missing contracts: a foundation importing a feature would pass everywhere "
        "but auth",
    ),
    waived(
        "the-registry-inverts-the-dependency",
        "The registry inverts the dependency so the foundation stays ignorant of its consumers.",
        "held for shared (surfaces-are-registered); auth resolving keys through ApiKeyQuery is "
        "not checked",
    ),
    waived(
        "one-process-wide-bus",
        "`host.events` is that same bus, wired at mount",
        "nothing asserts host.events is the bus singleton",
    ),
    # ── AGENTS Observability ──────────────────────────────────────────────────────────────
    held(
        "journal-reads-are-rls-scoped",
        "Reads are RLS-scoped",
        test_every_public_table_enforces_row_level_security,
    ),
    held(
        "only-the-journal-on-the-critical-path",
        "This is the one record the base lets sit on a request's critical path.",
        test_a_full_sink_and_a_full_capture_queue_leave_the_request_untouched,
    ),
    waived(
        "a-fact-has-no-severity",
        "A fact has no severity: it happened.",
        "nothing checks that neither the journal nor an event class carries a level",
    ),
    waived(
        "one-log-table-for-the-deployment",
        "one Postgres table the whole deployment shares",
        "no test runs two instances and reads one's lines from the other",
    ),
    held(
        "the-request-path-only-enqueues",
        "The request path only enqueues (a bounded deque)",
        test_processor_enqueues_without_writing,
    ),
    waived(
        "the-log-table-is-unlogged",
        "the table is `UNLOGGED`",
        "nothing reads log_lines' persistence, partitioning or commit mode; the migration "
        "alone says it",
    ),
    held(
        "the-log-write-is-one-multi-row-insert",
        "the write is one multi-row insert per drain",
        test_append_writes_the_whole_batch_as_one_statement,
    ),
    held(
        "retention-drops-a-partition",
        "a day past the window leaves as a `DROP`",
        test_retention_drops_a_whole_day_as_one_partition,
    ),
    held(
        "the-log-falls-back-to-day-files",
        "the batch falls back to per-day files",
        test_a_batch_the_store_refuses_lands_in_the_day_file,
        test_a_store_that_refuses_is_announced_once,
    ),
    waived(
        "the-log-level-is-live",
        "an admin can raise it to `WARNING` or `ERROR` to quiet an instance",
        "nothing raises the level and checks a lower line is dropped",
    ),
    held(
        "a-line-says-what-no-record-says",
        "A line says what no other record says already",
        test_no_log_line_spells_a_business_event_kind,
        test_a_served_request_leaves_exactly_one_finished_line,
    ),
    held(
        "two-levels-carry-the-rest",
        "Two levels carry the rest.",
        test_nothing_is_written_below_the_two_levels,
    ),
    waived(
        "warning-is-what-was-absorbed",
        "`warning` is **what the code could not carry through and absorbed**",
        "info lines are inventoried (info-is-a-surprise); warning lines are not",
    ),
    held(
        "libraries-join-at-warning",
        "The libraries' stdlib `logging` joins the same chain at `WARNING` and above",
        test_only_a_library_line_is_held_to_the_warning_floor,
    ),
    waived(
        "middlewares-are-plain-asgi",
        "The request middlewares are plain ASGI, not `BaseHTTPMiddleware`",
        "nothing checks the middleware stack's classes; one BaseHTTPMiddleware would only show "
        "as a correlation missing from the finished line",
    ),
    held(
        "issues-fold-by-fingerprint",
        "folded, by stack fingerprint, into an `Issue`",
        test_fingerprint_ignores_the_variable_message,
        test_fingerprint_distinguishes_exception_types,
    ),
    waived(
        "one-occurrence-per-failure",
        "one per failure, whatever else logs the same exception on its way out",
        "no bound test logs one exception twice and counts its occurrences",
    ),
    waived(
        "a-failing-tracker-worsens-nothing",
        "a failing tracker never worsens what it tracks",
        "no bound test makes a tracker raise and checks the others still receive the capture",
    ),
    waived(
        "answered-no-versus-broken",
        "the dependency *answered no*",
        "the gap of one-dependency-verdict: the verdict is unit-tested, nothing binds its "
        "callers to it",
    ),
    held(
        "the-park-opens-the-issue",
        "the park is what opens the issue",
        test_a_task_parked_for_good_is_captured_as_a_bug,
    ),
    held(
        "lifespan-workers-catch-everything",
        "The five lifespan workers catch everything",
        test_a_lifespan_loop_that_falls_over_opens_an_issue,
    ),
    held(
        "readiness-on-the-same-verdict",
        "The readiness probe is on the same verdict",
        test_a_readiness_probe_that_starts_failing_says_why,
    ),
    waived(
        "the-timeline-pins-names",
        "those pinned names are shown on the row and are what free text searches",
        "no scenario renames a subject and finds its old name on the timeline",
    ),
    held(
        "lines-inherit-the-correlation",
        "Lines and occurrences inherit the ids from contextvars",
        test_a_row_correlates_by_the_request_it_names,
    ),
    waived(
        "the-entity-filter-is-journal-only",
        "the per-entity filter narrows to the journal alone",
        "nothing filters by entity and checks the other sources drop out",
    ),
    waived(
        "the-timeline-says-its-sort-is-partial",
        "the screen says so rather than pass a sample off as an ordering",
        "no scenario sorts by another column and reads the notice",
    ),
    held(
        "the-timeline-sort-boundary-covers-reversed-time",
        "any sort other than newest-first orders the loaded page only",
        test_the_default_sort_claims_nothing,
        test_a_column_sort_says_it_only_orders_the_page,
        test_ascending_time_says_it_only_orders_the_page,
    ),
    held(
        "metrics-owns-the-counter-outright",
        "`apps/metrics` owns the counter outright.",
        test_no_shared_module_names_a_bounded_context,
    ),
    waived(
        "metrics-off-finds-nobody",
        "Switch the app off and the offer finds nobody",
        "nothing switches metrics off and checks the middleware still serves",
    ),
    held(
        "metrics-rolls-up-and-exports",
        "a daily rollup that downsamples minute → hour and applies retention",
        test_rollup_downsamples_old_minute_rows_then_purge_applies_retention,
        test_render_prometheus_exposes_cumulative_histogram,
    ),
    # ── AGENTS Conventions ────────────────────────────────────────────────────────────────
    waived(
        "dependencies-live-in-current-py",
        "Each context's FastAPI dependencies live in its own `contract/current.py`",
        "7 of 17 contexts have the file (ROADMAP); nothing checks where a dependency is declared",
    ),
    held(
        "the-rls-session-runs-on-app-rls",
        "`RlsSession` runs on `app_rls`",
        test_the_rls_session_runs_as_the_app_role_and_the_admin_one_does_not,
    ),
    held(
        "an-anonymous-caller-names-nobody",
        "An anonymous caller gets `app_rls` with claims naming nobody.",
        test_get_rls_session_gives_an_anonymous_caller_a_context_with_no_identity,
    ),
    waived(
        "pre-identity-reads-through-a-definer",
        "goes through a `SECURITY DEFINER` function executable by `app_rls` alone",
        "test_every_security_definer_function_pins_its_search_path checks their shape, not "
        "that each pre-identity read goes through one, nor who may run it",
    ),
    waived(
        "the-sign-in-methods",
        "Email/password with mailed confirmation",
        "each method has its scenarios; nothing checks this list against them",
    ),
    waived(
        "profile-actions-are-settings-gated",
        "are settings-gated (`profile.*_enabled`)",
        "nothing checks each flag gates its route",
    ),
    waived(
        "a-get-never-delivers-a-session",
        "a GET never delivers a session",
        "nothing walks the GET routes and checks none sets the auth cookies",
    ),
    waived(
        "sign-in-forwards-the-visitor",
        "forward the visitor's address to GoTrue as `Sb-Forwarded-For`",
        "nothing checks the header on the sign-in and sign-up calls",
    ),
    held(
        "recurring-jobs-reenqueue",
        "Recurring jobs (purges, rollups) re-enqueue themselves on completion.",
        test_recurring_task_reenqueues_next_run,
    ),
    held(
        "email-rides-the-queue",
        "Transactional email goes the same way",
        test_enqueue_email_outboxes_through_the_callers_session,
    ),
    held(
        "event-delivery-rides-the-queue",
        "Durable async event delivery rides the same queue",
        test_tick_enqueues_one_task_per_subscriber_and_marks_the_fact_dispatched,
    ),
    waived(
        "negotiation-goes-through-the-helpers",
        "centralize the JSON / fragment / page branching",
        "nothing checks a router branches only through these helpers",
    ),
    waived(
        "a-page-is-assembled-from-slices",
        "A full page's context is assembled from _slices_",
        "nothing checks a full page's context is built by the collector",
    ),
    held(
        "slice-collisions-rejected-at-startup",
        "collisions rejected at startup",
        test_register_fullpage_provider_rejects_a_duplicate_name,
        test_register_fullpage_provider_rejects_a_key_collision_across_two_names,
        test_register_fullpage_provider_rejects_a_key_colliding_with_the_seeded_context,
    ),
    held(
        "uuid7-minted-on-both-sides",
        "minted by the ORM where Python writes and by the database where it does not",
        test_every_mapped_primary_key_is_a_time_ordered_uuid7,
    ),
    held(
        "uuid7-lets-a-trail-page-on-its-key",
        "which is what lets an append-only trail page on its key",
        test_uuid7_is_time_ordered_and_versioned,
    ),
    waived(
        "ordering-across-two-minters",
        "across the two it is only as good as the agreement between the app's clock and the "
        "database's",
        "a stated limit, not a guarantee: nothing measures the skew between the two minters",
    ),
    waived(
        "daisyui-is-the-component-system",
        "daisyUI 5 is the component system",
        "the gap of one-component-system: the classes beating the layer are frozen, and the "
        "claim holds when that set is empty",
    ),
    waived(
        "component-classes-live-in-the-layer",
        "Project-specific component classes live in `@layer components`",
        "the same frozen set as one-component-system",
    ),
    waived(
        "reuse-components",
        "Reuse components instead of re-spelling utility chains",
        "a ratchet holds the two named chains (card-panel, the tab shell) at zero; nothing "
        "yet detects an arbitrary re-spelled chain",
    ),
    held(
        "icons-are-phosphor",
        "Icons are Phosphor.",
        test_every_icon_a_surface_declares_has_a_glyph_to_render,
        test_no_template_spells_an_icon_as_a_literal_glyph,
    ),
    waived(
        "markup-uses-landmarks-and-labels",
        "Markup uses real landmarks, labelled controls",
        "no accessibility audit runs over the rendered pages (markup-is-semantic-and-accessible)",
    ),
    waived(
        "drivers-share-a-substrate",
        "Both E2E drivers share a substrate",
        "nothing checks each feature mixin extends the shared drivers",
    ),
    waived(
        "each-scenario-leaves-nothing-behind",
        "The API driver wraps each scenario in a rolled-back transaction",
        "no test checks a scenario leaves no committed row behind, on either driver",
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
    held(
        "routers-own-http",
        "Routers own HTTP and nothing else — parsing, serialization, status codes; no business "
        "logic, no direct DB access.",
        test_no_router_reaches_the_database_itself,
    ),
    waived(
        "three-audiences",
        "Every business route answers three audiences from one handler",
        "the JSON and HTML faces are held (see two-faces); the third is not — nothing asks "
        "which routes actually have an HTMX fragment",
    ),
    held(
        "tests-live-with-their-context",
        "Templates, tests, and BDD steps live with their context",
        test_templates_tests_and_steps_live_with_their_context,
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
        test_every_fixed_route_wins_its_first_match,
    ),
    held(
        "surfaces-are-registered",
        "Because every surface is registered rather than hardcoded",
        test_no_shared_module_names_a_bounded_context,
    ),
    held(
        "contract-never-exports-a-settings-handle",
        "A contract never exports a settings handle",
        test_no_contract_exports_a_settings_handle,
    ),
    held(
        "no-magic-strings-in-collaboration",
        "Both key handlers by the Python type they carry, so there are no magic strings and no "
        "shared imports.",
        test_the_collaboration_registries_are_keyed_by_type_alone,
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
        test_the_signup_trigger_spells_the_fact_its_class_derives,
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
        test_the_emit_path_says_nothing_of_its_own,
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
        test_a_loop_that_comes_back_says_what_the_outage_cost,
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
    held(
        "request-finished-once-per-request",
        "Every served request leaves one `request.finished` line — including one whose handler "
        "raised",
        test_a_served_request_leaves_exactly_one_finished_line,
        test_a_request_whose_handler_raised_still_leaves_its_finished_line,
    ),
    held(
        "health-probe-exemption",
        "what the browser fetched by itself leaves nothing unless it 5xx'd",
        test_a_healthy_readiness_probe_leaves_no_line,
        test_a_healthy_liveness_probe_leaves_no_line,
        test_a_failing_readiness_probe_is_traced_at_error,
        test_a_failing_liveness_probe_is_traced_at_error,
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
        test_the_fact_that_opens_an_issue_points_back_at_the_request,
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
    held(
        "three-session-dependencies",
        "Three DB session dependencies: `RlsSession` (default — RLS enforced), "
        "`get_user_session` (raw), `AdminSession` (BYPASSRLS",
        test_the_session_dependencies_are_exactly_the_three_named,
    ),
    held(
        "enqueue-is-outbox",
        "`enqueue()` writes through the caller's session, so a task exists iff the business "
        "transaction commits (outbox semantics)",
        test_a_task_rolls_back_with_the_transaction_that_enqueued_it,
        test_worker_runs_enqueued_task,
    ),
    held(
        "the-limiter-fails-open",
        "The limiter fails open: a store it cannot reach lets the request through, because rate "
        "limiting must never be what takes an endpoint down",
        test_rate_limit_fails_open_when_store_is_down,
        test_a_store_the_limiter_cannot_reach_is_a_bug,
        test_a_store_that_never_answers_fails_open_within_its_timeout,
    ),
    held(
        "a-fact-is-fanned-out-once",
        "It claims what it dispatches in the transaction that stamps it",
        test_tick_enqueues_one_task_per_subscriber_and_marks_the_fact_dispatched,
        test_a_second_tick_does_not_refan_a_dispatched_fact,
    ),
    held(
        "csrf-without-tokens",
        "Cross-site mutations are rejected by a `Sec-Fetch-Site` middleware (CSRF protection "
        "without tokens)",
        test_a_cross_site_mutation_is_rejected_by_the_assembled_app,
    ),
    held(
        "fragments-are-standalone-markup",
        "Fragments are standalone valid markup (they're swapped into the live DOM).",
        test_no_fragment_response_starts_inside_a_table,
    ),
    held(
        "a-form-is-json-at-the-door",
        "re-encodes a urlencoded form as JSON before routing, so every mutation declares one "
        "Pydantic body that FastAPI validates and documents, and nothing reads `request.form()` "
        "by hand — a multipart upload passes through untouched.",
        test_a_form_reaches_the_handler_as_its_declared_body,
        test_a_multipart_upload_is_left_alone,
        test_every_mutation_declares_the_body_it_reads,
    ),
    held(
        "every-json-answer-names-its-model",
        "the API lane validates each answer it receives against the schema its route declares",
        test_every_json_face_declares_its_schema,
        test_an_answer_straying_from_its_schema_is_named_by_its_operation,
    ),
    held(
        "never-call-datetime-now",
        "`clock.now()` is the single source of time. Never call `datetime.now()`.",
        test_time_comes_from_the_one_clock,
    ),
    held(
        "tokens-stay-uuidv4",
        "Security tokens are the deliberate exception — they stay random **UUIDv4**",
        test_the_uuid4_exception_is_exactly_the_token_columns,
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
        test_the_snapshot_reads_in_assertions_are_the_named_ones,
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
    held(
        "one-composition-root",
        "One top-level module forms the composition root — the only place allowed to know several "
        "contexts at once: `main.py`.",
        test_the_composition_root_is_the_only_module_that_mounts,
    ),
    held(
        "schema-is-a-full-description",
        "the OpenAPI schema is a full description of the app",
        test_every_mutation_declares_the_body_it_reads,
        test_every_json_face_declares_its_schema,
        test_every_operation_has_its_own_id,
    ),
    waived(
        "client-is-generated",
        "It is generated\ncode: never edit it, re-run `make client-gen` after changing routes or "
        "DTOs.",
        "a drift shows up as a failing perf smoke, which is a slow and indirect way to say it",
    ),
    held(
        "env-test-is-committed",
        "`.env.test` is committed and uses `127.0.0.1`.",
        test_the_test_environment_file_is_committed_and_local,
    ),
    held(
        "documented-commands-exist",
        "make finalize     # js-build + fix + lint + test (run before committing)",
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
UNHELD_TODAY = 57
