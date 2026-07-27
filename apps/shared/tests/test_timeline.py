"""Business-events timeline — the feed projection is rich and never leaks the raw kind/payload."""

from apps.shared import clock
from apps.shared.events.models import BusinessEventLog
from apps.shared.events.timeline import activity_entries


def _row(
    *,
    kind="todo.created",
    icon="clipboard-text",
    user_name=None,
    entity_name=None,
    ts=None,
):
    # The readable names are columns, not payload keys: they are pinned at write time so the feed
    # stays legible once the actor or the org they name is gone.
    return BusinessEventLog(
        created_at=ts or clock.now(),
        kind=kind,
        icon=icon,
        user_id=None,
        org_id=None,
        entity_id=None,
        request_id=None,
        payload={},
        user_name=user_name,
        entity_name=entity_name,
    )


def test_activity_entries_surface_who_what_which_document():
    """The feed shows the actor, the humanized verb and the object's own name — never the kind."""
    [entry] = activity_entries([_row(user_name="alice", entity_name="Ship the Q3 report")])
    assert entry.who == "alice"
    assert entry.label == "Created"  # humanized from the kind, verb only
    assert entry.detail == "Ship the Q3 report"  # the "which document"
    assert "todo.created" not in (entry.label, entry.detail)  # raw kind never surfaces


def test_activity_entries_drop_the_actor_on_the_users_own_trail():
    """The profile feed is all the viewer's own actions, so repeating 'who' is noise."""
    [entry] = activity_entries([_row(user_name="alice")], show_actor=False)
    assert entry.who is None


def test_activity_entries_take_an_href_from_the_surface_link():
    """Each surface supplies its own deep link (entity page, filtered logs…) via ``link``."""
    row = _row(kind="pages.created")
    [entry] = activity_entries([row], link=lambda r: f"/go/{r.kind}")
    assert entry.href == "/go/pages.created"
    [plain] = activity_entries([row])  # no link → no href, rendered as text
    assert plain.href is None
