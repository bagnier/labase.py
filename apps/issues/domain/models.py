import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, Timestamped, UUIDPk, Versioned


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
    status: Mapped[str] = mapped_column(default=IssueStatus.new)
    count: Mapped[int] = mapped_column(BigInteger, default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_version: Mapped[str] = mapped_column(default="dev")
    last_version: Mapped[str] = mapped_column(default="dev")
    resolved_in_version: Mapped[str | None] = mapped_column(default=None)


class Occurrence(Base, UUIDPk):
    """One sighting of an issue, with the JSONB context that pivots to the firehose.

    ``id`` is a UUIDv7 (via ``UUIDPk``): time-ordered, so the newest-first cursor page
    (``order_by(id.desc())`` + ``id < before_id``) keeps working without a bigint sequence."""

    __tablename__ = "issue_occurrences"

    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class IssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: IssueStatus
    count: int
    first_seen: datetime
    last_seen: datetime
    first_version: str
    last_version: str
    resolved_in_version: str | None


class OccurrenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    context: dict[str, Any]
