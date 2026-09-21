"""GET / with no featured org: the signed-in state must show, not "Sign in"."""


def test_signed_in_visitor_sees_no_sign_in_prompt(driver):
    client = driver.client_for("home-signed-in@example.com")

    body = client.get("/").text

    assert "Sign in" not in body
    assert 'href="/profile"' in body
