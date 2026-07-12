"""The dashboard "Recent activity" timeline — the org's own audit trail, labels only."""

from apps.auth.tests.given_helpers import user_id_for_email
from apps.organizations.tests.given_helpers import orgs_for_user
from apps.shared.observability.audit import _insert_audit_log

_EMAIL = "dashboard-activity@example.com"


def test_dashboard_lists_the_orgs_recent_business_events(driver):
    client = driver.client_for(_EMAIL)
    user_id = user_id_for_email(_EMAIL)
    org = orgs_for_user(user_id)[0]
    driver.run(
        _insert_audit_log("info", "calendar.event_created", user_id, None, org["id"], None, {})
    )

    body = client.get(f"/{org['handle']}/dashboard", headers={"accept": "text/html"}).text

    section = body.split("data-recent-activity")[1].split("</section>")[0]
    assert "Event created" in section  # the event key, humanised
    assert "calendar.event_created" not in section  # raw keys and payloads stay internal
