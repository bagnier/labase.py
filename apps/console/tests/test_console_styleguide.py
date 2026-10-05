def test_appearance_tab_renders_component_gallery(driver):
    driver.sign_in_as_admin("styleguide-admin@example.com")
    body = driver.client().get("/console/settings", headers={"accept": "text/html"}).text
    # Each section is a landmark labelled by its heading (id="<section>-h").
    for section in ("sg-buttons", "sg-alerts", "sg-cards", "sg-forms", "sg-table"):
        assert f'id="{section}"' in body
        assert f'aria-labelledby="{section}-h"' in body
        assert f'id="{section}-h"' in body


def test_appearance_tab_applies_app_theme(driver):
    driver.sign_in_as_admin("styleguide-admin2@example.com")
    body = driver.client().get("/console/settings", headers={"accept": "text/html"}).text
    assert 'data-theme="labase-light"' in body


def test_appearance_tab_loads_the_chart_scripts(driver):
    """Without charts.js, the charts are inert markup that still has every id."""
    driver.sign_in_as_admin("styleguide-admin3@example.com")

    body = driver.client().get("/console/settings", headers={"accept": "text/html"}).text

    assert ["apexcharts.min.js" in body, "charts.js" in body] == [True, True]
