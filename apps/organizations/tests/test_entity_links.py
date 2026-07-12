"""Deep-link resolution for activity-feed entries — the entity's member page, where one exists."""

from apps.organizations.contract.entity_links import entity_url


def test_resolves_the_org_scoped_page_for_apps_with_a_detail_route():
    assert entity_url("pages.created", "my-slug", "acme") == "/acme/pages/my-slug"
    assert entity_url("calendar.event_created", "42", "acme") == "/acme/calendar/42"


def test_encodes_the_entity_id_into_the_path():
    assert entity_url("pages.created", "a b/c", "acme") == "/acme/pages/a%20b%2Fc"


def test_no_link_when_app_has_no_detail_route_or_data_is_missing():
    assert entity_url("todo.created", "1", "acme") is None  # no member detail page for todos
    assert entity_url("pages.created", None, "acme") is None  # no entity
    assert entity_url("pages.created", "my-slug", None) is None  # org handle unknown (cross-org)
