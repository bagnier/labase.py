"""One overview card raising must not take the whole dashboard down with it."""

from unittest.mock import patch

from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.shared.integration.contribs import Contribs


async def _overview_with_a_missing_template(query: OverviewQuery) -> Overview:
    return Overview(
        key="broken",
        title="Broken card",
        icon="bug",
        href="broken",
        template="organizations/_does_not_exist.html",
    )


def test_a_cards_missing_template_does_not_500_the_dashboard(driver):
    """A registry of its own, holding the broken card alone: no mounted app can be made to
    return a template that does not exist, so the failure is staged by the provider."""
    driver.sign_in_as_member_of_org("dashboard-broken-card@example.com", "Acme")
    broken = Contribs()
    broken.provide(OverviewQuery, _overview_with_a_missing_template)

    with patch("apps.organizations.infra.router.contribs", broken):
        response = driver.client().get(
            f"/{driver.active_org_handle}/dashboard", headers={"accept": "text/html"}
        )

    assert (response.status_code, "Broken card" in response.text) == (200, False)
