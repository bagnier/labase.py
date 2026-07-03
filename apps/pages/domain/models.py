import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared import clock
from apps.shared.persistence.base import Base


class PageVisibility(StrEnum):
    """Increasing exposure: a draft is private to the org's members, ``members`` is
    readable by every member, ``public`` is readable by anonymous visitors too."""

    draft = "draft"
    members = "members"
    public = "public"


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String)
    slug: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(String, default="")
    visibility: Mapped[PageVisibility] = mapped_column(String, default=PageVisibility.draft)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )

    __mapper_args__ = {"version_id_col": version}


class PageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    slug: str
    visibility: PageVisibility
    created_at: datetime


class PageNavItem(Base):
    __tablename__ = "page_nav_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pages.id"))
    position: Mapped[int] = mapped_column(default=0)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )

    __mapper_args__ = {"version_id_col": version}


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
