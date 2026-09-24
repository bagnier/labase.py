"""The todo list's own content negotiation — full page, fragment, or JSON."""


def test_a_history_restore_of_the_todo_list_gets_the_full_page_not_the_fragment(driver):
    """htmx sends ``HX-Request`` on a back-navigation too, but swaps the whole document rather
    than the list alone — so a restore of a pushed ``/{org}/todos`` URL needs the shell, not the
    fragment the same headers would otherwise pick."""
    driver.sign_in_as_fresh_user()
    slug = driver.active_org_handle

    body = (
        driver.client()
        .get(
            f"/{slug}/todos",
            headers={
                "accept": "text/html",
                "HX-Request": "true",
                "HX-History-Restore-Request": "true",
            },
        )
        .text
    )

    assert "<html" in body
