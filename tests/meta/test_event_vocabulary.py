"""The event vocabulary across apps: subjects in ``user_id``, ``org_id``, ``entity_id``, which the
console filters and links read, never a private ``passkey_id``. Here, not in ``apps/shared``,
which may not import the apps.
"""

import ast
import re
from dataclasses import MISSING, fields
from pathlib import Path

import apps.main  # noqa: F401 — fills the catalog
from apps.auth.contract.events import UserCreated
from apps.shared.events import BusinessEvent, OrgScoped
from apps.shared.events.catalog import catalog

_BASE_SLOTS = {"user_id", "org_id", "entity_id"}

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"
_MIGRATIONS = _ROOT / "supabase" / "migrations"


def _shipped_events() -> dict[str, type[BusinessEvent]]:
    """The catalog without test-defined classes, whose presence depends on import order."""
    return {
        kind: cls
        for kind, cls in catalog.kinds().items()
        if cls.__module__.startswith("apps.") and ".tests." not in cls.__module__
    }


# Every kind emitted today. They are stored data: renaming one is a migration, since old records
# keep the old spelling and stop being rebuilt.
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
    """Derived kinds keep matching what the journal stores."""
    assert set(_shipped_events()) == _KINDS


def test_every_event_names_both_of_its_halves():
    """A concrete event without its `verb` would get no kind and never be rebuilt."""
    unnamed = {
        cls.__name__ for cls in _shipped_events().values() if not (cls.app_name and cls.verb)
    }
    assert unnamed == set()


# Identity-shaped fields outside the three slots, allowed as values only, each with its reason.
_IDENTITY_NAMED = re.compile(r"(^|_)(id|handle|slug|email|key|username|login)$")
_IDENTITY_NAMED_FIELDS = {
    # The value itself: the address asked for, the handle chosen.
    "auth.email_change_requested.new_email",
    "auth.user_created.email",
    "profile.handle_changed.new_handle",
    # A page's slug at the time, beside its `entity_id`.
    "pages.created.slug",
    "pages.deleted.slug",
    "pages.published_members.slug",
    "pages.published_public.slug",
    "pages.slug_changed.slug",
    "pages.unpublished.slug",
    "pages.updated.slug",
    # A settings row has no surrogate pk: `key` with no `entity_id`.
    "settings.org_override_removed.key",
    "settings.org_override_set.key",
    "settings.server_changed.key",
}


def test_no_event_names_an_identity_outside_the_bases_slots():
    """A private identity hides the subject from the entity filter. Every identity-shaped name,
    slugs and handles included."""
    named = {
        f"{kind}.{f.name}"
        for kind, cls in _shipped_events().items()
        for f in fields(cls)
        if _IDENTITY_NAMED.search(f.name) and f.name not in _BASE_SLOTS
    }
    assert named == _IDENTITY_NAMED_FIELDS


def test_the_catalog_is_actually_populated():
    # Guards the guard: an empty catalog would make it vacuous.
    assert len(_shipped_events()) > 30


def test_an_org_scoped_event_declares_its_org_as_required():
    """An org's fact mixes in OrgScoped, so it cannot be built without its org."""
    slack = {
        f"{kind}"
        for kind, cls in _shipped_events().items()
        if issubclass(cls, OrgScoped)
        for f in fields(cls)
        if f.name == "org_id" and f.default is not MISSING
    }
    assert slack == set()


def test_only_org_scoped_events_carry_an_org_at_all():
    """A server-wide fact has no org field."""
    strays = {
        kind
        for kind, cls in _shipped_events().items()
        if not issubclass(cls, OrgScoped) and any(f.name == "org_id" for f in fields(cls))
    }
    assert strays == set()


# Words of refusal: a verb built on one names what did not happen.
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
    """(AGENTS: business events are facts, not sagas) No refusal verb, no `emit` in an
    `except`."""
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
    bodies = [
        body
        for path in sorted(_MIGRATIONS.glob("*.sql"))
        for body in re.findall(
            r"function public\.handle_new_user\(\).*?\$\$;", path.read_text(), re.DOTALL
        )
    ]
    return bodies[-1]


def test_the_signup_trigger_spells_the_fact_its_class_derives():
    """The signup trigger writes `UserCreated` in SQL: a verb renamed on one side only would make
    every signup unroutable."""
    written = re.search(
        r"insert into public\.business_events \(app_name, verb, icon.*?"
        r"values \('([\w-]+)', '([\w-]+)', '([\w-]+)'",
        _signup_trigger_body(),
        re.DOTALL,
    )

    assert written is not None
    assert written.groups() == (UserCreated.app_name, UserCreated.verb, UserCreated.icon)
