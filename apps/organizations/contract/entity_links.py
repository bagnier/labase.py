"""Deep links for activity-feed entries — map a business event to the org-scoped member page for
the entity it concerns, so a dashboard/profile timeline entry is clickable ("go to that page").

Only apps that expose a member detail route resolve; every other event stays plain text. Keyed by
the event's own ``app_name`` and the entity's uuid pk (``entity_id``).
Owned here because ``organizations`` owns the org-handle route namespace (:data:`ORG_PREFIX`); the
templates are data, so this pulls in no cross-app imports.
"""

import uuid
from urllib.parse import quote

# App name → the org-scoped route template for one of its entities (``{id}`` is always a uuid pk).
# Extend it as apps grow a member-facing detail page; an app that is absent simply never links. One
# with only a list page links to that list, anchored on the item's ``<app>-<id>``. Pages route
# through ``by-id``, which redirects to the page's current slug URL — the slug can change, the uuid
# cannot.
_ENTITY_ROUTES = {
    "pages": "/{handle}/pages/by-id/{id}",
    "calendar": "/{handle}/calendar/{id}",
    "todo": "/{handle}/todos#todo-{id}",
    "files": "/{handle}/files#file-{id}",
}


def entity_url(app_name: str, entity_id: uuid.UUID | None, org_handle: str | None) -> str | None:
    """The member page for a business event's entity, or ``None`` when the app has no detail route
    (or the fact lacks the entity/handle needed to build one)."""
    if not entity_id or not org_handle:
        return None
    template = _ENTITY_ROUTES.get(app_name)
    if not template:
        return None
    return template.format(handle=org_handle, id=quote(str(entity_id), safe=""))
