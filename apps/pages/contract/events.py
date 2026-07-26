"""Pages' business events — a page's authoring lifecycle on the shared trail.

Create/delete use the CRUD abstracts; every other change is a form of *update* (a re-slug, a
publish, an unpublish) so it derives from :class:`~apps.shared.events.EntityUpdated` with a
domain ``verb`` — giving each a distinct ``kind`` (``"pages.published_public"`` …). Every page
event carries its ``slug``; the persister on the ``BusinessEvent`` base records them.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated


@dataclass(frozen=True, kw_only=True)
class PageEvent(BusinessEvent):
    entity: ClassVar[str] = "pages"
    icon: ClassVar[str] = "file-text"
    # The page's stable identity is its uuid pk, carried on the base's ``entity_id`` — it survives a
    # re-slug, so the logs viewer's per-entity filter keeps a renamed page's timeline together.
    # ``slug`` rides in the payload for display and for resolving the deep link to the current URL.
    slug: str | None = None


@dataclass(frozen=True, kw_only=True)
class PageCreated(PageEvent, EntityCreated):
    pass


@dataclass(frozen=True, kw_only=True)
class PageDeleted(PageEvent, EntityDeleted):
    pass


@dataclass(frozen=True, kw_only=True)
class PageUpdated(PageEvent, EntityUpdated):
    pass


@dataclass(frozen=True, kw_only=True)
class PageSlugChanged(PageEvent, EntityUpdated):
    verb: ClassVar[str] = "slug_changed"


@dataclass(frozen=True, kw_only=True)
class PagePublishedMembers(PageEvent, EntityUpdated):
    verb: ClassVar[str] = "published_members"


@dataclass(frozen=True, kw_only=True)
class PagePublishedPublic(PageEvent, EntityUpdated):
    verb: ClassVar[str] = "published_public"


@dataclass(frozen=True, kw_only=True)
class PageUnpublished(PageEvent, EntityUpdated):
    verb: ClassVar[str] = "unpublished"
