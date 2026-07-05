from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, Timestamped, Versioned


class IssueStatus(StrEnum):
    new = "new"
    unresolved = "unresolved"
    resolved = "resolved"
    ignored = "ignored"
    regressed = "regressed"


class ErrorGroup(Base, Versioned, Timestamped):
    """One *issue*: every event sharing a stack fingerprint, with its lifecycle."""

    __tablename__ = "error_groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str]
    status: Mapped[str] = mapped_column(default=IssueStatus.new)
    count: Mapped[int] = mapped_column(BigInteger, default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_version: Mapped[str] = mapped_column(default="dev")
    last_version: Mapped[str] = mapped_column(default="dev")
    resolved_in_version: Mapped[str | None] = mapped_column(default=None)


class ErrorEvent(Base):
    """One occurrence, with the JSONB context that pivots to the structured logs."""

    __tablename__ = "error_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("error_groups.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ErrorGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: IssueStatus
    count: int
    first_seen: datetime
    last_seen: datetime
    first_version: str
    last_version: str
    resolved_in_version: str | None


class ErrorEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    context: dict[str, Any]
