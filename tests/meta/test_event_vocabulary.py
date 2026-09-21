"""One invariant over the whole event vocabulary: an event names its subject the way the base does.

``BusinessEvent`` offers three correlation slots — ``user_id`` (who acted), ``org_id`` (where) and
``entity_id`` (what it concerns) — and the console is built on them: the per-entity filter and the
deep links read ``entity_id``, the timeline's *detail* reads ``entity_name``. An event that stores
its subject under a private name (``group_id``, ``passkey_id``…) is therefore invisible to the
filter and renders without a detail, however carefully it was declared.

This lives in ``tests/meta`` rather than in ``apps/shared/tests`` because it is a cross-app
invariant:
shared may not import a bounded context, so only the composition root may see every vocabulary at
once (the same reason ``test_listener`` checks topics by string).
"""

import ast
import re
from dataclasses import MISSING, fields
from pathlib import Path

import apps.main  # noqa: F401  — mounting every app fills the catalog
from apps.auth.contract.events import UserCreated
from apps.shared.events import BusinessEvent, OrgScoped
from apps.shared.events.catalog import catalog

# The base's own scoping slots — the only id-shaped fields an event may declare.
_BASE_SLOTS = {"user_id", "org_id", "entity_id"}

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"
_MIGRATIONS = _ROOT / "supabase" / "migrations"


def _shipped_events() -> dict[str, type[BusinessEvent]]:
    """The product's vocabulary. The catalog is process-global (a class registers itself once, at
    import), so a full-suite run also holds the throwaway event classes the tests define — they are
    fixtures, not vocabulary, and asserting over them would make this pass or fail depending on
    what pytest imported first."""
    return {
        kind: cls
        for kind, cls in catalog.kinds().items()
        if cls.__module__.startswith("apps.") and ".tests." not in cls.__module__
    }


# Every kind the product emits *today* — not every kind the journal holds: a retired one keeps its
# records, which the timeline still renders from their own columns, and leaves this set. These
# strings are stored data, so *renaming* one is what costs: records keep the old spelling, the
# listener stops reconstructing them and their consumers stop firing. Adding a line is routine;
# retiring one means no code emits it any more; renaming one is a migration, not a refactor.
_KINDS = {
    "accounts.deleted",
    "accounts.disabled",
    "accounts.enabled",
    "api_keys.created",
    "api_keys.revoked",
    "auth.confirmation_resent",
    "auth.email_change_requested",
    "auth.email_changed",
    "auth.impersonation_started",
    "auth.impersonation_stopped",
    "auth.passkey_added",
    "auth.passkey_removed",
    "auth.password_changed",
    "auth.password_reset",
    "auth.signed_in",
    "auth.signed_out",
    "auth.twofa_enabled",
    "auth.user_created",
    "auth.user_deleted",
    "calendar.created",
    "calendar.deleted",
    "calendar.updated",
    "files.deleted",
    "files.renamed",
    "files.share_downloaded",
    "files.share_link_created",
    "files.uploaded",
    "issues.opened",
    "issues.regressed",
    "issues.status_changed",
    "learning.reviewed",
    "organizations.created",
    "organizations.handle_changed",
    "organizations.invitation_revoked",
    "organizations.invitation_sent",
    "organizations.member_joined",
    "organizations.member_left",
    "organizations.member_removed",
    "organizations.member_role_changed",
    "organizations.renamed",
    "pages.created",
    "pages.deleted",
    "pages.published_members",
    "pages.published_public",
    "pages.slug_changed",
    "pages.unpublished",
    "pages.updated",
    "profile.account_deleted",
    "profile.avatar_updated",
    "profile.handle_changed",
    "settings.admin_granted",
    "settings.admin_revoked",
    "settings.org_override_removed",
    "settings.org_override_set",
    "settings.server_changed",
    "todo.created",
    "todo.deleted",
    "todo.edited",
    "todo.ticked",
    "todo.unticked",
}


def test_the_stored_vocabulary_is_exactly_what_history_expects():
    """No kind is hand-written any more: each is derived from its app mixin's `app_name` plus the
    event's `verb`. That derivation must keep producing the strings already in the journal — this
    pins them, so a typo in a verb or a family reshuffle fails here and not in production."""
    assert set(_shipped_events()) == _KINDS


def test_every_event_names_both_of_its_halves():
    """An event's identity *is* its two halves — the composition into `kind` happens by construction
    here (BusinessEvent.__init_subclass__) and in the database (a generated column), so there is
    nothing left to drift. What can still go wrong is a half left unsaid: a family mixin gives
    `app_name` for free, so a concrete event that forgets its `verb` silently gets no kind at all
    and never enters the catalog the listener rebuilds from."""
    unnamed = {
        cls.__name__ for cls in _shipped_events().values() if not (cls.app_name and cls.verb)
    }
    assert unnamed == set()


# A field named like an identity — an id, a handle, a slug, an email, a key — outside the base's
# three slots. Each is a subject the per-entity filter cannot see unless it is only a *value*: what
# a change set, or the readable name riding beside an `entity_id` that already correlates.
_IDENTITY_NAMED = re.compile(r"(^|_)(id|handle|slug|email|key|username|login)$")
_IDENTITY_NAMED_FIELDS = {
    # The value the fact is about: the address registered or asked for, the handle chosen.
    "auth.email_change_requested.new_email",
    "auth.user_created.email",
    "profile.handle_changed.new_handle",
    # A page's slug as of the fact, beside the `entity_id` that correlates it.
    "pages.created.slug",
    "pages.deleted.slug",
    "pages.published_members.slug",
    "pages.published_public.slug",
    "pages.slug_changed.slug",
    "pages.unpublished.slug",
    "pages.updated.slug",
    # The one subject named by a handle alone: a settings row has no surrogate pk, so these carry
    # `key` with `entity_id` null — the exception the ROADMAP's Identity item names.
    "settings.org_override_removed.key",
    "settings.org_override_set.key",
    "settings.server_changed.key",
}


def test_no_event_names_an_identity_outside_the_bases_slots():
    """An identity in a payload field is one the base already has a home for. Keeping a private one
    doesn't just duplicate it — it hides the subject from the console's per-entity filter. Read off
    every identity-shaped name, not only `*_id`: a slug or a handle is the renameable kind the
    README rules out. What is left is named above, each with the reason it may."""
    named = {
        f"{kind}.{f.name}"
        for kind, cls in _shipped_events().items()
        for f in fields(cls)
        if _IDENTITY_NAMED.search(f.name) and f.name not in _BASE_SLOTS
    }
    assert named == _IDENTITY_NAMED_FIELDS


def test_the_catalog_is_actually_populated():
    # Guards the guard: an empty catalog would make the assertion above vacuously true.
    assert len(_shipped_events()) > 30


def test_an_org_scoped_event_declares_its_org_as_required():
    """Scope is a property of the event *type*. An event that only makes sense inside an org must
    say so by mixing in OrgScoped, which makes org_id required — so a fact that would land
    unscoped (and be silently hidden by RLS from the org's own timeline) cannot be built at all."""
    slack = {
        f"{kind}"
        for kind, cls in _shipped_events().items()
        if issubclass(cls, OrgScoped)
        for f in fields(cls)
        if f.name == "org_id" and f.default is not MISSING
    }
    assert slack == set()


def test_only_org_scoped_events_carry_an_org_at_all():
    """The converse: org_id is no longer a slot every event drags along. A server-wide fact (an
    admin grant, an issue) has no org field to leave empty."""
    strays = {
        kind
        for kind, cls in _shipped_events().items()
        if not issubclass(cls, OrgScoped) and any(f.name == "org_id" for f in fields(cls))
    }
    assert strays == set()


# What a refusal is called. A verb built on one of these names something that did not happen —
# the wrong password, the blocked change, the denied route — which is a log line, not a fact.
_REFUSAL_WORDS = {
    "attempted",
    "blocked",
    "denied",
    "failed",
    "forbidden",
    "invalid",
    "refused",
    "rejected",
    "unauthorized",
    "wrong",
}


def test_only_what_happened_is_a_fact():
    """ "A refused attempt … changed nothing, so it is a structured log line, not a fact." A fact
    about nothing takes two shapes, both absent: a verb that names the refusal, and an `emit`
    written inside an `except` — the place a refusal is caught. Whether every emitted fact really
    changed a row is the half no walk can read."""
    refusing = {
        kind for kind in _shipped_events() if set(kind.split(".")[1].split("_")) & _REFUSAL_WORDS
    }
    emitted_on_failure = {
        f"{path.relative_to(_ROOT)}:{call.lineno}"
        for path in sorted(_APPS.rglob("*.py"))
        if "/tests/" not in path.as_posix()
        for handler in ast.walk(ast.parse(path.read_text()))
        if isinstance(handler, ast.ExceptHandler)
        for call in ast.walk(handler)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "emit"
    }

    assert (refusing, emitted_on_failure) == (set(), set())


def _signup_trigger_body() -> str:
    """The last definition of `handle_new_user` across the migrations — a later one replaces it."""
    bodies = [
        body
        for path in sorted(_MIGRATIONS.glob("*.sql"))
        for body in re.findall(
            r"function public\.handle_new_user\(\).*?\$\$;", path.read_text(), re.DOTALL
        )
    ]
    return bodies[-1]


def test_the_signup_trigger_spells_the_fact_its_class_derives():
    """The one fact Python never emits: `UserCreated` is recorded by the signup trigger, on
    GoTrue's own transaction, in SQL literals no derivation reaches. The class is what the
    listener rebuilds the fact from, so a verb renamed on one side only lands every signup as an
    unroutable fact — no personal org, no seeds — while the vocabulary tests stay green."""
    written = re.search(
        r"insert into public\.business_events \(app_name, verb, icon.*?"
        r"values \('([\w-]+)', '([\w-]+)', '([\w-]+)'",
        _signup_trigger_body(),
        re.DOTALL,
    )

    assert written is not None
    assert written.groups() == (UserCreated.app_name, UserCreated.verb, UserCreated.icon)
