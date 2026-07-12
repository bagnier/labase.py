"""Deep links for activity-feed entries — map a business event to the org-scoped member page for
the entity it concerns, so a dashboard/profile timeline row is clickable ("go to that page").

Only apps that expose a member detail route resolve; every other event stays plain text. Keyed by
the event's app segment (``kind`` is ``"<app>.<verb>"``) and the entity's own id (a page slug, a
calendar event id). Owned here because ``organizations`` owns the org-handle route namespace
(:data:`ORG_PREFIX`); the templates are data, so this pulls in no cross-app imports.
"""

from urllib.parse import quote

# app segment → org-scoped route template ({handle}, {id} = entity_id). Extend as apps grow a
# member-facing detail page; unknown apps simply don't link.
_ENTITY_ROUTES = {
    "pages": "/{handle}/pages/{id}",  # id is the slug
    "calendar": "/{handle}/calendar/{id}",
}


def entity_url(kind: str, entity_id: str | None, org_handle: str | None) -> str | None:
    """The member page for a business event's entity, or ``None`` when the app has no detail route
    (or the row lacks the entity/handle needed to build one)."""
    if not entity_id or not org_handle:
        return None
    template = _ENTITY_ROUTES.get(kind.split(".", 1)[0])
    if not template:
        return None
    return template.format(handle=org_handle, id=quote(entity_id, safe=""))
