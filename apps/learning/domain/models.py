import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared import clock
from apps.shared.persistence.base import Base, OrgScoped, Timestamped, UUIDPk, Versioned


class Outcome(StrEnum):
    learned = "learned"
    again = "again"


class Deck(Base, UUIDPk, OrgScoped, Versioned, Timestamped):
    __tablename__ = "decks"
    __table_args__ = (UniqueConstraint("org_id", "name", name="decks_org_name_unique"),)

    name: Mapped[str]
    resource: Mapped[str | None] = mapped_column(default=None)
    position: Mapped[int] = mapped_column(default=0)


class Card(Base, UUIDPk, OrgScoped, Versioned, Timestamped):
    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint("deck_id", "external_id", name="cards_deck_external_unique"),
    )

    deck_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"))
    external_id: Mapped[str]
    question: Mapped[str]
    answer: Mapped[str]
    resource: Mapped[str | None] = mapped_column(default=None)
    position: Mapped[int] = mapped_column(default=0)


class DeckSubscription(Base, UUIDPk, OrgScoped, Versioned):
    __tablename__ = "deck_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "deck_id", name="deck_subscriptions_user_deck_unique"),
    )

    user_id: Mapped[uuid.UUID]
    deck_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )


class CardState(Base, UUIDPk, OrgScoped, Versioned):
    """Per-user learning progress for a card. Absence ⇒ level 0 (never studied)."""

    __tablename__ = "card_states"
    __table_args__ = (UniqueConstraint("user_id", "card_id", name="card_states_user_card_unique"),)

    user_id: Mapped[uuid.UUID]
    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    level: Mapped[int] = mapped_column(default=0)
    last_reviewed_on: Mapped[date | None] = mapped_column(Date, default=None)
    next_review_on: Mapped[date | None] = mapped_column(Date, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )


class ReviewCardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    question: str
    level: int
    deck: str


class ResourceRead(BaseModel):
    deck: str
    resource: str


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
    deck_resource: str | None
    card_resource: str | None
