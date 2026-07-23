"""The dashboard "Recent activity" timeline — the org's own business events, labels only."""

from apps.auth.tests.given_helpers import user_id_for_email
from apps.shared.events.store import insert_business_event

_EMAIL = "dashboard-activity@example.com"


def _personal_org(client) -> dict:
    """The signup-provisioned personal org, read over HTTP so it comes from the driver's own
    (rolled-back) transaction — a direct SQL helper on a separate connection could not see it."""
    return client.get("/organizations").json()[0]


def test_dashboard_lists_the_orgs_recent_business_events(driver):
    client = driver.client_for(_EMAIL)
    user_id = user_id_for_email(_EMAIL)
    org = _personal_org(client)
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
    # The activity block sits above the apps' overview cards — no longer the page's last section.
    assert body.index("data-org-activity") < body.index("grid grid-cols-1 sm:grid-cols-2 gap-4")


def test_activity_fragment_groups_by_day_and_filters_by_type(driver):
    client = driver.client_for(_EMAIL)
    user_id = user_id_for_email(_EMAIL)
    org = _personal_org(client)
    for kind in ("calendar.event_created", "todo.created"):
        driver.run(
            insert_business_event(
                kind=kind,
                level="info",
                user_id=user_id,
                ip=None,
                org_id=org["id"],
                request_id=None,
                payload=None,
            )
        )

    fragment = client.get(
        f"/{org['handle']}/dashboard/activity",
        params={"app": "todo"},
        headers={"accept": "text/html"},
    ).text

    assert "Today" in fragment  # newest-first entries land in a day-grouped section
    assert "Created" in fragment  # todo.created, humanised
    assert "Event created" not in fragment  # the type filter narrows to todo.* only
