"""The activity feed: readable, never the raw kind or payload."""

from apps.shared import clock
from apps.shared.events.activity import activity_entries
from apps.shared.events.models import BusinessEventRecord


def _record(
    *,
    app_name="todo",
    verb="created",
    icon="clipboard-text",
    user_name=None,
    entity_name=None,
    ts=None,
):
    return BusinessEventRecord(
        created_at=ts or clock.now(),
        app_name=app_name,
        verb=verb,
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
    [entry] = activity_entries([_record(user_name="alice", entity_name="Ship the Q3 report")])
    assert entry.who == "alice"
    assert entry.label == "Created"
    assert entry.detail == "Ship the Q3 report"
    assert "todo.created" not in (entry.label, entry.detail)


def test_activity_entries_drop_the_actor_on_the_users_own_trail():
    [entry] = activity_entries([_record(user_name="alice")], show_actor=False)
    assert entry.who is None


def test_activity_entries_take_an_href_from_the_surface_link():
    record = _record(app_name="pages")
    [entry] = activity_entries([record], link=lambda r: f"/go/{r.app_name}")
    assert entry.href == "/go/pages"
    [plain] = activity_entries([record])
    assert plain.href is None
