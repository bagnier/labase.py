"""Links from an activity-feed entry to its entity's page, by ``app_name`` and ``entity_id``.
Here because organizations owns the ``/{org_handle}`` namespace; the templates are plain strings,
so no app is imported.
"""

import uuid
from urllib.parse import quote

# App → route template for an entity (``{id}`` is its uuid); an absent app never links. A list
# page links with the item's ``<app>-<id>`` anchor. Pages go through ``by-id``: slugs change.
_ENTITY_ROUTES = {
    "pages": "/{handle}/pages/by-id/{id}",
    "calendar": "/{handle}/calendar/{id}",
    "todo": "/{handle}/todos#todo-{id}",
    "files": "/{handle}/files#file-{id}",
}


def entity_url(app_name: str, entity_id: uuid.UUID | None, org_handle: str | None) -> str | None:
    """The entity's page, or ``None`` when there is no route or no entity."""
    if not entity_id or not org_handle:
        return None
    template = _ENTITY_ROUTES.get(app_name)
    if not template:
        return None
    return template.format(handle=org_handle, id=quote(str(entity_id), safe=""))
