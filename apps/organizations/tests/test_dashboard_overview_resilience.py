"""One overview card raising must not take the whole dashboard down with it."""

from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.shared.integration.host import host


async def _overview_with_a_missing_template(query: OverviewQuery) -> Overview:
    return Overview(
        key="broken",
        title="Broken card",
        icon="bug",
        href="broken",
        template="organizations/_does_not_exist.html",
    )


def test_a_cards_missing_template_does_not_500_the_dashboard(driver):
    driver.sign_in_as_member_of_org("dashboard-broken-card@example.com", "Acme")
    host.contribs.provide(OverviewQuery, _overview_with_a_missing_template)
    try:
        response = driver.client().get(
            f"/{driver.active_org_handle}/dashboard", headers={"accept": "text/html"}
        )
    finally:
        host.contribs._providers[OverviewQuery].remove(_overview_with_a_missing_template)

    assert response.status_code == 200
    assert "Broken card" not in response.text
