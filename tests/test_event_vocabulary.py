"""One invariant over the whole event vocabulary: an event names its subject the way the base does.

``BusinessEvent`` offers three correlation slots — ``user_id`` (who acted), ``org_id`` (where) and
``entity_id`` (what it concerns) — and the console is built on them: the per-entity filter and the
deep links read ``entity_id``, the timeline's *detail* reads ``entity_name``. An event that stores
its subject under a private name (``group_id``, ``passkey_id``…) is therefore invisible to the
filter and renders without a detail, however carefully it was declared.

This lives at the root rather than in ``apps/shared/tests`` because it is a cross-app invariant:
shared may not import a bounded context, so only the composition root may see every vocabulary at
once (the same reason ``test_listener`` checks topics by string).
"""

from dataclasses import MISSING, fields

import apps.main  # noqa: F401  — mounting every app fills the catalog
from apps.shared.events import BusinessEvent, OrgScoped
from apps.shared.events.catalog import catalog

# The base's own scoping slots — the only id-shaped fields an event may declare.
_BASE_SLOTS = {"user_id", "org_id", "entity_id"}


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
    # No kind is hand-written any more: each is derived from its app mixin's `app_name` plus the
    # event's `verb`. That derivation must keep producing the strings already in the journal —
    # this pins them, so a typo in a verb or a family reshuffle fails here and not in production.
    assert set(_shipped_events()) == _KINDS


def test_every_event_names_both_of_its_halves():
    # An event's identity *is* its two halves — the composition into `kind` happens by construction
    # here (BusinessEvent.__init_subclass__) and in the database (a generated column), so there is
    # nothing left to drift. What can still go wrong is a half left unsaid: a family mixin gives
    # `app_name` for free, so a concrete event that forgets its `verb` silently gets no kind at all
    # and never enters the catalog the listener rebuilds from.
    unnamed = {
        cls.__name__ for cls in _shipped_events().values() if not (cls.app_name and cls.verb)
    }
    assert unnamed == set()


def test_no_event_names_an_identity_outside_the_bases_slots():
    # An `*_id` payload field is an identity the base already has a home for. Keeping a private one
    # doesn't just duplicate it — it hides the subject from the console's per-entity filter.
    offenders = {
        f"{kind}.{f.name}"
        for kind, cls in _shipped_events().items()
        for f in fields(cls)
        if f.name.endswith("_id") and f.name not in _BASE_SLOTS
    }
    assert offenders == set()


def test_the_catalog_is_actually_populated():
    # Guards the guard: an empty catalog would make the assertion above vacuously true.
    assert len(_shipped_events()) > 30


def test_an_org_scoped_event_declares_its_org_as_required():
    # Scope is a property of the event *type*. An event that only makes sense inside an org must
    # say so by mixing in OrgScoped, which makes org_id required — so a fact that would land
    # unscoped (and be silently hidden by RLS from the org's own timeline) cannot be built at all.
    slack = {
        f"{kind}"
        for kind, cls in _shipped_events().items()
        if issubclass(cls, OrgScoped)
        for f in fields(cls)
        if f.name == "org_id" and f.default is not MISSING
    }
    assert slack == set()


def test_only_org_scoped_events_carry_an_org_at_all():
    # The converse: org_id is no longer a slot every event drags along. A server-wide fact
    # (an admin grant, an issue) has no org field to leave empty.
    strays = {
        kind
        for kind, cls in _shipped_events().items()
        if not issubclass(cls, OrgScoped) and any(f.name == "org_id" for f in fields(cls))
    }
    assert strays == set()
