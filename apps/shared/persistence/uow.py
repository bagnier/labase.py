"""Ambient request unit-of-work — the current transaction's session, for durable event fan-out.

``emit(event)`` must enqueue outbox rows on the *same* session (transaction) as the mutation it
accompanies, so a durable event exists iff the mutation commits (outbox semantics). Threading
that session through every producer would be noise, so the request's single RLS session is bound
here by ``get_rls_session`` and read back by the outbox fan-out. A request runs on exactly one
session with a single commit at function-stack teardown, so the ambient session is unambiguous.

Non-request callers (queue handlers, startup, signup's admin-session work) never bind this — they
pass a session explicitly to the fan-out instead.
"""

from contextvars import ContextVar, Token

from sqlalchemy.ext.asyncio import AsyncSession

_current_session: ContextVar[AsyncSession | None] = ContextVar("current_session", default=None)


def bind_current_session(session: AsyncSession) -> Token:
    """Bind the request's session as the ambient unit of work; returns a reset token."""
    return _current_session.set(session)


def reset_current_session(token: Token) -> None:
    """Restore the previous binding (called in the request dependency's ``finally``)."""
    _current_session.reset(token)


def current_session() -> AsyncSession | None:
    """The ambient request session, or ``None`` outside a request unit of work."""
    return _current_session.get()
