"""Business-events store — the write path degrades safely, and the feed projection is rich."""

from datetime import timedelta
from unittest.mock import patch

import pytest

from apps.shared import clock
from apps.shared.observability.business_events import (
    BusinessEventRow,
    _ago,
    activity_entries,
    insert_business_event,
)


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
    assert _ago(now - delta, now) == expected


@pytest.mark.asyncio
async def test_failed_write_logs_a_warning_instead_of_raising():
    # Regression: the warning must not pass `event=`/`kind=` under structlog's positional
    # message key, and a lost row must never crash the fire-and-forget write task.
    with (
        patch(
            "apps.shared.observability.business_events.admin_session_factory",
            side_effect=RuntimeError("db down"),
        ),
        patch("apps.shared.observability.business_events.log") as log,
    ):
        await insert_business_event(
            kind="auth.signed_in",
            level="info",
            user_id="not-a-uuid",
            ip=None,
            org_id=None,
            request_id=None,
            payload=None,
        )
    log.warning.assert_called_once_with(
        "business_event.write_failed", kind="auth.signed_in", user_id="not-a-uuid"
    )
