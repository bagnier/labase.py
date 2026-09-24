"""The Load screen's content negotiation — full page, JSON, or the drill-down fragment."""


def test_the_load_screen_answers_the_full_page_when_hx_request_is_false(driver):
    """The issue's own reproduction: any non-empty string is truthy in Python, so a check
    reading the raw header's presence — instead of comparing it to ``"true"`` — answers the
    ``metrics/_detail.html`` drill-down fragment even though the header says ``"false"``."""
    driver.seed_traffic("GET /console", requests=1, errors=0, around_ms=20)
    driver.sign_in_as_admin("metrics-admin-hx-false@example.com")

    response = driver.client().get(
        "/console/load", headers={"accept": "text/html", "HX-Request": "false"}
    )

    assert (response.status_code, 'id="load-detail"' in response.text) == (200, True)
