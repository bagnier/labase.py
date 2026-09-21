"""What a signed-in user outside the org reads of its pages — ``public_pages`` decides, on the RLS
connection, not a Python filter over a BYPASSRLS one."""

_OWNER = "pages-owner@example.com"
_OUTSIDER = "pages-outsider@example.com"


def _org_with_one_page_per_visibility(driver) -> str:
    owner = driver.client_for(_OWNER)
    handle = owner.get("/organizations").json()[0]["handle"]
    for title, visibility in (("Draft", None), ("Internal", "members"), ("Public", "public")):
        slug = title.lower()
        owner.post(f"/{handle}/pages", json={"title": title, "slug": slug}).raise_for_status()
        if visibility:
            owner.post(
                f"/{handle}/pages/{slug}/visibility", json={"visibility": visibility}
            ).raise_for_status()
    return handle


def test_a_signed_in_outsider_lists_only_the_public_pages(driver):
    handle = _org_with_one_page_per_visibility(driver)

    listed = driver.client_for(_OUTSIDER).get(f"/{handle}/pages").json()

    assert [page["title"] for page in listed] == ["Public"]


def test_a_signed_in_outsider_cannot_tell_a_members_page_from_a_missing_one(driver):
    handle = _org_with_one_page_per_visibility(driver)
    outsider = driver.client_for(_OUTSIDER)

    statuses = [outsider.get(f"/{handle}/pages/{s}").status_code for s in ("internal", "nope")]

    assert statuses == [404, 404]
