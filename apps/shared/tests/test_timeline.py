"""Business-events timeline — the feed projection is rich and never leaks the raw kind/payload."""

from datetime import timedelta

import pytest

from apps.shared import clock
from apps.shared.events.models import BusinessEventRow
from apps.shared.events.timeline import activity_entries, ago


def _row(*, kind="todo.created", level="info", icon="clipboard-text", payload=None, ts=None):
    return BusinessEventRow(
        ts=ts or clock.now(),
        level=level,
        kind=kind,
        icon=icon,
        org_id=None,
        user_id=None,
        entity_id=None,
        request_id=None,
        payload=payload or {},
    )


def test_activity_entries_surface_who_what_which_document():
    """The feed shows the actor, the humanized verb and the object's own name — never the kind."""
    [entry] = activity_entries([_row(payload={"actor": "alice", "label": "Ship the Q3 report"})])
    assert entry["who"] == "alice"
    assert entry["label"] == "Created"  # humanized from the kind, verb only
    assert entry["detail"] == "Ship the Q3 report"  # the "which document"
    assert "todo.created" not in (entry["label"], entry["detail"])  # raw kind never surfaces


def test_activity_entries_drop_the_actor_on_the_users_own_trail():
    """The profile feed is all the viewer's own actions, so repeating 'who' is noise."""
    [entry] = activity_entries([_row(payload={"actor": "alice"})], show_actor=False)
    assert entry["who"] is None


def test_activity_entries_carry_level_for_the_node_colour():
    [entry] = activity_entries([_row(level="warning", kind="auth.password_changed")])
    assert entry["level"] == "warning"


def test_activity_entries_take_an_href_from_the_surface_link():
    """Each surface supplies its own deep link (entity page, filtered logs…) via ``link``."""
    row = _row(kind="pages.created")
    [entry] = activity_entries([row], link=lambda r: f"/go/{r.kind}")
    assert entry["href"] == "/go/pages.created"
    [plain] = activity_entries([row])  # no link → no href, rendered as text
    assert plain["href"] is None


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "just now"),
        (timedelta(minutes=3), "3m ago"),
        (timedelta(hours=4), "4h ago"),
        (timedelta(days=2), "2d ago"),
    ],
)
def test_ago_is_a_compact_relative_moment(delta, expected):
    now = clock.now()
    assert ago(now - delta, now) == expected
