import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, DateTime, ForeignKey, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, Created, Timestamped, UUIDPk, Versioned


class IssueStatus(StrEnum):
    new = "new"
    unresolved = "unresolved"
    resolved = "resolved"
    ignored = "ignored"
    regressed = "regressed"


class Issue(Base, UUIDPk, Versioned, Timestamped):
    """One *issue*: every occurrence sharing a stack fingerprint, with its lifecycle."""

    __tablename__ = "issues"

    fingerprint: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str]
    status: Mapped[IssueStatus] = mapped_column(
        SAEnum(IssueStatus, name="issue_status", create_type=False), default=IssueStatus.new
    )
    occurrence_count: Mapped[int] = mapped_column(BigInteger, default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The app release, not the optimistic-lock `version` this table also carries.
    first_release: Mapped[str] = mapped_column(default="dev")
    last_release: Mapped[str] = mapped_column(default="dev")
    resolved_in_release: Mapped[str | None] = mapped_column(default=None)


class Occurrence(Base, UUIDPk, Created):
    """One sighting of an issue, with the JSONB context that pivots to the log sink.

    ``id`` is a UUIDv7 (via ``UUIDPk``): time-ordered, so the newest-first cursor page
    (``order_by(id.desc())`` + ``id < before_id``) keeps working without a bigint sequence."""

    __tablename__ = "issue_occurrences"

    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id"))
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class IssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: IssueStatus
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime
    first_release: str
    last_release: str
    resolved_in_release: str | None


class OccurrenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    context: dict[str, Any]
