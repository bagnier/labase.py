"""Deep links for activity-feed entries — map a business event to the org-scoped member page for
the entity it concerns, so a dashboard/profile timeline row is clickable ("go to that page").

Only apps that expose a member detail route resolve; every other event stays plain text. Keyed by
the event's app segment (``kind`` is ``"<app>.<verb>"``) and the entity's uuid pk (``entity_id``).
Owned here because ``organizations`` owns the org-handle route namespace (:data:`ORG_PREFIX`); the
templates are data, so this pulls in no cross-app imports.
"""

import uuid
from urllib.parse import quote

# app segment → org-scoped route template ({handle}, {id} = entity_id, always a uuid pk). Extend
# as apps grow a member-facing detail page; unknown apps simply don't link. Apps with only a list
# page (no per-entity detail route) link to that list with an anchor on the item's `<app>-<id>`.
# Pages route via `by-id`, which redirects to the page's current slug URL (the slug can change, so
# the uuid is the stable link target).
_ENTITY_ROUTES = {
    "pages": "/{handle}/pages/by-id/{id}",
    "calendar": "/{handle}/calendar/{id}",
    "todo": "/{handle}/todos#todo-{id}",
    "files": "/{handle}/files#file-{id}",
}


def entity_url(kind: str, entity_id: uuid.UUID | None, org_handle: str | None) -> str | None:
    """The member page for a business event's entity, or ``None`` when the app has no detail route
    (or the row lacks the entity/handle needed to build one)."""
    if not entity_id or not org_handle:
        return None
    template = _ENTITY_ROUTES.get(kind.split(".", 1)[0])
    if not template:
        return None
    return template.format(handle=org_handle, id=quote(str(entity_id), safe=""))
