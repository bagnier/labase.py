"""The profile "Recent activity" timeline — the user's own audit trail, labels only."""

from apps.auth.tests.given_helpers import user_id_for_email
from apps.shared.observability.audit import _insert_audit_log

_EMAIL = "recent-activity@example.com"


def test_profile_page_lists_the_users_own_recent_actions(driver):
    client = driver.client_for(_EMAIL)
    user_id = user_id_for_email(_EMAIL)
    driver.run(_insert_audit_log("info", "todo.task_created", user_id, None, None, None, {}))

    body = client.get("/profile", headers={"accept": "text/html"}).text

    section = body.split("data-recent-activity")[1].split("</section>")[0]
    assert "Task created" in section  # the event key, humanised
    assert "todo.task_created" not in section  # raw keys and payloads stay internal
