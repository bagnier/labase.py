"""GET / with no featured org: the signed-in state must show, not "Sign in"."""

from tests.e2e.drivers.api_base import VISITOR


def _cta_lines(body: str) -> list[str]:
    fragment = body.split('<div class="flex flex-col gap-3">')[1].split("</div>", maxsplit=1)[0]
    return [line.strip() for line in fragment.splitlines() if line.strip()]


def test_signed_in_visitor_sees_a_profile_link(driver):
    client = driver.client_for("home-signed-in@example.com")

    body = client.get("/").text

    assert _cta_lines(body) == [
        '<a href="/profile" class="btn btn-primary w-full">Go to your profile</a>'
    ]


def test_signed_out_visitor_sees_sign_in_and_register_links(driver):
    body = driver.client_for(VISITOR).get("/").text

    assert _cta_lines(body) == [
        '<a href="/auth/login" class="btn btn-primary w-full">Sign in</a>',
        '<a href="/auth/register" class="btn w-full">Create an account</a>',
    ]
