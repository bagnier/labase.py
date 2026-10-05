"""The Load screen's faces: full page, JSON, drill-down fragment."""


def test_the_load_screen_answers_the_full_page_when_hx_request_is_false(driver):
    """``HX-Request: false`` is not an HTMX request."""
    driver.seed_traffic("GET /console", requests=1, errors=0, around_ms=20)
    driver.sign_in_as_admin("metrics-admin-hx-false@example.com")

    response = driver.client().get(
        "/console/load", headers={"accept": "text/html", "HX-Request": "false"}
    )

    assert (response.status_code, 'id="load-detail"' in response.text) == (200, True)
