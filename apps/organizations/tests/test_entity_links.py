"""Activity-feed links to the entity's page."""

import uuid

from apps.organizations.contract.entity_links import entity_url


def test_resolves_the_org_scoped_page_for_apps_with_a_detail_route():
    eid = uuid.uuid7()
    assert entity_url("pages", eid, "acme") == f"/acme/pages/by-id/{eid}"
    assert entity_url("calendar", eid, "acme") == f"/acme/calendar/{eid}"


def test_resolves_a_list_anchor_for_apps_with_only_a_list_page():
    # No detail page: the list, anchored on the item.
    eid = uuid.uuid7()
    assert entity_url("todo", eid, "acme") == f"/acme/todos#todo-{eid}"
    assert entity_url("files", eid, "acme") == f"/acme/files#file-{eid}"


def test_no_link_when_app_has_no_detail_route_or_data_is_missing():
    eid = uuid.uuid7()
    assert entity_url("learning", eid, "acme") is None
    assert entity_url("pages", None, "acme") is None
    assert entity_url("pages", eid, None) is None
