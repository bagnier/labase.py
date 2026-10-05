"""A page's authoring facts; each change has its own verb (``pages.published_public``…) and
carries the ``slug``.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated, OrgScoped
from apps.shared.vocabulary import AppName, PhosphorIcon


@dataclass(frozen=True, kw_only=True)
class PageEvent(OrgScoped, BusinessEvent):
    app_name: ClassVar[AppName] = "pages"
    icon: ClassVar[PhosphorIcon] = "file-text"
    # ``entity_id`` survives a re-slug, keeping the page's history together; ``slug`` is for
    # display.
    slug: str


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
