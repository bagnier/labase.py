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
    slug: str | None = None

    def __post_init__(self) -> None:
        # A page's stable id *is* its slug — mirror it into the systematic entity_id correlation
        # column so pages join todos/files/… in the logs viewer's per-entity filter.
        if self.entity_id is None and self.slug is not None:
            object.__setattr__(self, "entity_id", self.slug)


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
