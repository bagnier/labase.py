"""Deep-link resolution for activity-feed entries — the entity's member page, where one exists."""

import uuid

from apps.organizations.contract.entity_links import entity_url


def test_resolves_the_org_scoped_page_for_apps_with_a_detail_route():
    # entity_id is the entity's uuid pk; pages route via by-id, which redirects to the current slug.
    eid = uuid.uuid7()
    assert entity_url("pages", eid, "acme") == f"/acme/pages/by-id/{eid}"
    assert entity_url("calendar", eid, "acme") == f"/acme/calendar/{eid}"


def test_resolves_a_list_anchor_for_apps_with_only_a_list_page():
    # Todos & files have no per-entity detail route — they link to the list, anchored on the item.
    eid = uuid.uuid7()
    assert entity_url("todo", eid, "acme") == f"/acme/todos#todo-{eid}"
    assert entity_url("files", eid, "acme") == f"/acme/files#file-{eid}"


def test_no_link_when_app_has_no_detail_route_or_data_is_missing():
    eid = uuid.uuid7()
    assert entity_url("learning", eid, "acme") is None  # app has no route at all
    assert entity_url("pages", None, "acme") is None  # no entity
    assert entity_url("pages", eid, None) is None  # org handle unknown (cross-org)
