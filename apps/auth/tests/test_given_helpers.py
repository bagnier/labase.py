from uuid import uuid4

from apps.auth.tests.given_helpers import create_user, delete_user
from tests.e2e.sql_setup import run_sql


def test_deleting_a_created_user_leaves_no_event_of_theirs_behind():
    """The signup trigger journals ``UserCreated`` in GoTrue's own committed transaction, and the
    journal has no FK to auth.users: an event left behind is re-delivered by every later drain."""
    uid = create_user(f"{uuid4()}@test.local", "Secret1!")
    delete_user(uid)
    rows = run_sql(
        "SELECT kind FROM business_events WHERE user_id = :uid", {"uid": uid}, fetch=True
    )
    assert rows == []
