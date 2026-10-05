"""An occurrence's request id links to the Timeline filtered on it."""

_ADMIN = "issue-pivots@example.com"
_TITLE = "ValueError: pivot boom"


def test_an_occurrence_links_its_request_back_to_the_timeline(driver):
    driver.sign_in_as_admin(_ADMIN)
    driver.seed_captured_error(_TITLE, count=1)
    listed = driver.client().get("/console/issues", headers={"accept": "application/json"}).json()
    issue_id = next(i["id"] for i in listed if i["title"] == _TITLE)

    body = driver.client().get(f"/console/issues/{issue_id}", headers={"accept": "text/html"}).text

    assert 'href="/console/timeline?request_id=' in body
