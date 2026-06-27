def test_styleguide_returns_200(driver):
    response = driver.client().get("/styleguide")
    assert response.status_code == 200


def test_styleguide_renders_component_sections(driver):
    body = driver.client().get("/styleguide").text
    # Each section is a landmark labelled by its heading (id="<section>-h") so
    # accessibility tooling — and these tests — can target it by role/label, not CSS.
    for section in ("sg-buttons", "sg-alerts", "sg-cards", "sg-forms", "sg-table"):
        assert f'id="{section}"' in body
        assert f'aria-labelledby="{section}-h"' in body
        assert f'id="{section}-h"' in body


def test_styleguide_applies_app_theme(driver):
    # The theme is an app-wide console setting rendered into <html data-theme>, not a switcher.
    body = driver.client().get("/styleguide").text
    assert 'data-theme="light"' in body
