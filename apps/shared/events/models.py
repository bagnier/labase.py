"""The shape of a business event on the journal.

One data structure, no behaviour: :class:`BusinessEventRecord` is the ORM mapping of the append-only
``business_events`` table — the single shape written on ``emit`` *and* handed back on a read (the
session keeps ``expire_on_commit=False``, so a read record stays usable past its session). Access
logic — writing and querying it — lives in the repository; humanizing a record for a surface is in
:mod:`apps.shared.events.activity`.

This model maps only the columns that *are the fact* — the ones a reader projects and a consumer
rebuilds. The delivery-plumbing column ``dispatched_at`` (the listener's claim cursor) is
deliberately **not** mapped here: it is queue mechanics, not part of what happened, and the listener
touches it through raw SQL in :mod:`apps.shared.events.repository` (alongside the ``consumed``
ledger). Keeping it off the model is what lets this class stay "the fact, and only the fact"; the
choice lives here so the absence reads as intent, not oversight.
"""

import uuid
from typing import Any

from sqlalchemy import Computed
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, Created, UUIDPk


class BusinessEventRecord(Base, UUIDPk, Created):
    """The append-only business-event record. Members read their own / their orgs' facts via RLS.

    One writer: the ``record_business_event`` SECURITY DEFINER function. ``emit`` calls it on
    the session the caller names, so the fact commits atomically with the mutation; the function
    inserts as its owner, so no raw table INSERT grant is exposed — a member (or a PostgREST client
    on the same role) can no longer POST the journal table directly. That session is usually the
    caller's own RLS (``authenticated``) one; the auth routes pass the **BYPASSRLS admin** session
    instead, since a caller signing in or out has no RLS identity to write under. The signup trigger
    is the one exception: it inserts directly, itself SECURITY DEFINER, because user creation
    happens in GoTrue's transaction with no app session to join. Attribution is the emitter's to get
    right — a durable consumer legitimately records a fact for an actor that isn't its session's
    identity — so the function trusts the supplied ``user_id`` rather than re-checking it. The
    listener's dispatch (admin session) and every read are unchanged.

    ``id`` is a UUIDv7 (via ``UUIDPk``): time-ordered, so it stays the monotonic cursor the listener
    claims/scans on and the newest-first feeds order by — no bigint sequence.

    Each correlation key is paired with the readable name it had *then*: the journal outlives its
    subjects (a closed account, a deleted or renamed org) and RLS hides a co-member's handle at read
    time. Every name is nullable — a system fact has no actor, a server-wide one no org, a pure-id
    subject no name, and work outside a request no request."""

    __tablename__ = "business_events"

    app_name: Mapped[str]
    verb: Mapped[str]
    kind: Mapped[str] = mapped_column(
        Computed("app_name || '.' || verb", persisted=True), nullable=False
    )
    icon: Mapped[str] = mapped_column(default="circle")
    user_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    user_name: Mapped[str | None] = mapped_column(default=None)
    org_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    org_name: Mapped[str | None] = mapped_column(default=None)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    entity_name: Mapped[str | None] = mapped_column(default=None)
    request_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    # "GET /profile", bound at request time: without it the request id resolves only while the
    # log sink still holds that request's lines, and would be opaque for good past that retention.
    request_name: Mapped[str | None] = mapped_column(default=None)
    ip_address: Mapped[str | None] = mapped_column(default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
