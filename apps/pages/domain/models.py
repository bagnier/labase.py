import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, OrgScoped, Timestamped, UUIDPk, Versioned


class PageVisibility(StrEnum):
    """Increasing exposure: a draft is private to the org's members, ``members`` is
    readable by every member, ``public`` is readable by anonymous visitors too."""

    draft = "draft"
    members = "members"
    public = "public"


class Page(Base, UUIDPk, OrgScoped, Versioned, Timestamped):
    __tablename__ = "pages"

    user_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String)
    slug: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(String, default="")
    visibility: Mapped[PageVisibility] = mapped_column(String, default=PageVisibility.draft)


class PageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    slug: str
    visibility: PageVisibility
    created_at: datetime


class PageNavItem(Base, UUIDPk, OrgScoped, Versioned, Timestamped):
    __tablename__ = "page_nav_items"

    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pages.id"))
    position: Mapped[int] = mapped_column(default=0)


class NavCandidate(BaseModel):
    """A published page with its current nav status — used by the nav manager."""

    page_id: uuid.UUID
    slug: str
    title: str
    visibility: PageVisibility
    in_nav: bool
    position: int | None


class NavItemRead(BaseModel):
    """A page currently in the nav, in order."""

    page_id: uuid.UUID
    slug: str
    title: str
    visibility: PageVisibility
