"""The Load screen's content negotiation — full page, JSON, or the drill-down fragment."""


def test_the_load_screen_answers_the_full_page_when_hx_request_is_false(driver):
    """``HX-Request: false`` is what a browser's own fetch sends on a plain navigation —
    truthiness on the raw header would read it as an HTMX request and answer the fragment."""
    driver.sign_in_as_admin("metrics-admin-hx-false@example.com")

    body = (
        driver.client()
        .get("/console/load", headers={"accept": "text/html", "HX-Request": "false"})
        .text
    )

    assert "<html" in body
