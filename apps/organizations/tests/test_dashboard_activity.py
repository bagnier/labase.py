"""The dashboard "Recent activity" timeline — the org's own business events, labels only."""

from apps.auth.tests.given_helpers import user_id_for_email
from apps.organizations.tests.given_helpers import orgs_for_user
from apps.shared.observability.business_events import insert_business_event

_EMAIL = "dashboard-activity@example.com"


def test_dashboard_lists_the_orgs_recent_business_events(driver):
    client = driver.client_for(_EMAIL)
    user_id = user_id_for_email(_EMAIL)
    org = orgs_for_user(user_id)[0]
    driver.run(
        insert_business_event(
            kind="calendar.event_created",
            level="info",
            user_id=user_id,
            ip=None,
            org_id=org["id"],
            request_id=None,
            payload=None,
        )
    )

    body = client.get(f"/{org['handle']}/dashboard", headers={"accept": "text/html"}).text

    section = body.split("data-recent-activity")[1].split("</section>")[0]
    assert "Event created" in section  # the event key, humanised
    assert "calendar.event_created" not in section  # raw keys and payloads stay internal
