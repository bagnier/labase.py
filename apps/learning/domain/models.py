import uuid
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import (
    Base,
    Created,
    OrgScoped,
    Timestamped,
    UUIDPk,
    Versioned,
)


class Outcome(StrEnum):
    learned = "learned"
    again = "again"


class Deck(Base, UUIDPk, OrgScoped, Versioned, Timestamped):
    __tablename__ = "decks"
    __table_args__ = (UniqueConstraint("org_id", "name"),)

    name: Mapped[str]
    resource_url: Mapped[str | None] = mapped_column(default=None)
    position: Mapped[int] = mapped_column(default=0)


class Card(Base, UUIDPk, OrgScoped, Versioned, Timestamped):
    __tablename__ = "cards"
    __table_args__ = (UniqueConstraint("deck_id", "external_id"),)

    deck_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"))
    external_id: Mapped[str]
    question: Mapped[str]
    answer: Mapped[str]
    resource_url: Mapped[str | None] = mapped_column(default=None)
    position: Mapped[int] = mapped_column(default=0)


class DeckSubscription(Base, UUIDPk, OrgScoped, Versioned, Created):
    __tablename__ = "deck_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "deck_id"),)

    user_id: Mapped[uuid.UUID]
    deck_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"))


class CardState(Base, UUIDPk, OrgScoped, Versioned, Created):
    """Per-user learning progress for a card. Absence ⇒ level 0 (never studied)."""

    __tablename__ = "card_states"
    __table_args__ = (UniqueConstraint("user_id", "card_id"),)

    user_id: Mapped[uuid.UUID]
    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    level: Mapped[int] = mapped_column(default=0)
    last_reviewed_on: Mapped[date | None] = mapped_column(Date, default=None)
    next_review_on: Mapped[date | None] = mapped_column(Date, default=None)


class ReviewCardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    question: str
    level: int
    deck: str


class ResourceRead(BaseModel):
    deck: str
    resource_url: str


# ── Pure value objects consumed by the spaced-repetition service ──────────────


@dataclass(frozen=True)
class Schedule:
    level: int
    last_reviewed_on: date
    next_review_on: date


@dataclass(frozen=True)
class DueCard:
    external_id: str
    level: int
    deck_position: int
    card_position: int
    next_review_on: date | None  # None ⇒ never studied (level 0)


@dataclass(frozen=True)
class CardResource:
    deck: str
    deck_position: int
    card_position: int
    deck_resource_url: str | None
    card_resource_url: str | None
