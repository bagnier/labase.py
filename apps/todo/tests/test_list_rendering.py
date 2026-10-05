"""The todo list's faces: page, fragment, JSON."""


def test_a_history_restore_of_the_todo_list_gets_the_full_page_not_the_fragment(driver):
    """A history restore sends ``HX-Request`` but replaces the whole document."""
    driver.sign_in_as_fresh_user()
    slug = driver.active_org_handle
    client = driver.client()

    restored = client.get(
        f"/{slug}/todos",
        headers={
            "accept": "text/html",
            "HX-Request": "true",
            "HX-History-Restore-Request": "true",
        },
    ).text
    plain = client.get(f"/{slug}/todos", headers={"accept": "text/html"}).text

    assert restored == plain
