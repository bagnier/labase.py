"""Driver-agnostic seeding for the timeline scenarios.

Two of the three sources are seeded through their real writers:
- request lines → the log repository's own append (``LogRepository.append``);
- business events → the shared ``BusinessEventRecord`` model.

Issue occurrences are the exception. The production path — emitting ``ExceptionCaptured`` —
records through the app's *shared* engine (``admin_session_factory``), which asyncpg can't be
driven from the browser driver's seed thread while the app is live (cross-loop corruption). So
issues are written directly through the driver's own session; because the ``error_*`` tables are
private to the issues context (the import-linter contract forbids importing its models), this is
the one place a raw insert is warranted — it also lets a fixture backdate ``created_at`` freely.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from apps.shared import clock
from apps.shared.events.models import BusinessEventRecord

# Deterministic ids so a seed step and a filter step agree on "Acme" / "alice@…" without needing
# a real org/user row (the timeline filters by the raw id it stored).
_NS = uuid.UUID("00000000-0000-0000-0000-00000000da7a")

# The scenarios call these "request log entries", so they are seeded under the logger the
# request tracer really writes with — stated here rather than imported, since production has
# no reason to export it: the timeline reads the name only for a line's app axis.
_REQUEST_LOGGER = "apps.shared.logs.request"


def timeline_org_id(name: str) -> str:
    return str(uuid.uuid5(_NS, f"org:{name}"))


def timeline_user_id(email: str) -> str:
    return str(uuid.uuid5(_NS, f"user:{email}"))


def timeline_request_id(token: str) -> str:
    """A scenario names a request "r-100"; the journal stores a uuid. Same trick as orgs and users:
    map the readable token to a stable uuid5 so the Gherkin stays plain language."""
    return str(uuid.uuid5(_NS, f"request:{token}"))


def _uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def event_model(
    event: str,
    *,
    org: str | None = None,
    user: str | None = None,
    when: datetime | None = None,
    request_id: str | None = None,
    request_name: str | None = None,
    entity_name: str | None = None,
) -> BusinessEventRecord:
    """A ready-to-``add`` business-event row — the same model ``emit`` writes, with an
    explicit ``created_at`` so a fixture can predate the current day (the writer can't backdate).

    The scenarios name an event the way it reads on screen (``"todo.created"``), so this is where
    that sentence becomes the two columns a row stores — ``kind`` itself is generated from them."""
    app_name, _, verb = event.partition(".")
    return BusinessEventRecord(
        created_at=when or clock.now(),
        app_name=app_name,
        verb=verb,
        user_id=_uuid(user),
        org_id=_uuid(org),
        request_id=_uuid(request_id),
        request_name=request_name,
        entity_id=uuid.uuid7() if entity_name else None,
        entity_name=entity_name,
    )


def event_run(count: int, org: str, *, now: datetime) -> list[BusinessEventRecord]:
    """``count`` facts of one org, a minute apart, **oldest first** — the order to add them in.

    Oldest first is not cosmetic. The journal pages on ``id desc`` (a uuid7, minted by the insert)
    while the timeline sorts on ``created_at``, and production keeps the two in step for free:
    ``created_at`` is the column default, stamped by the very statement that mints the id. A
    fixture that backdates ``created_at`` breaks that tie unless it inserts in the same order, and
    what it then measures is a state the product cannot reach — the source handing back its
    *oldest* rows as if they were its newest.

    A distinct ``entity_name`` per row, because a paging assertion has to tell one row from the
    next: every fact here is a ``todo.created``, so the kind cannot say which page a row came from.
    """
    return [
        event_model(
            "todo.created",
            org=org,
            when=now - timedelta(minutes=i),
            entity_name=f"fact {i:03d}",
        )
        for i in reversed(range(count))
    ]


def log_line(
    event: str,
    *,
    org: str | None = None,
    user: str | None = None,
    level: str = "info",
    when: datetime | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "timestamp": (when or clock.now()).isoformat(),
        "level": level,
        "logger": _REQUEST_LOGGER,
        "event": event,
        "org_id": org,
        "user_id": user,
        "request_id": request_id,
    }


def error_context(
    *, org: str | None = None, user: str | None = None, request_id: str | None = None
) -> dict[str, str]:
    return {
        k: v
        for k, v in {"org_id": org, "user_id": user, "request_id": request_id}.items()
        if v is not None
    }


# Issue occurrences: an issue (by fingerprint) plus one occurrence carrying the context.
INSERT_ISSUE = text(
    "INSERT INTO issues (fingerprint, title, first_seen, last_seen) "
    "VALUES (:fp, :title, :ts, :ts) RETURNING id"
)
INSERT_OCCURRENCE = text(
    "INSERT INTO issue_occurrences (issue_id, created_at, context) "
    "VALUES (:iid, :ts, CAST(:context AS jsonb))"
)


def issue_params(title: str, when: datetime | None = None) -> dict[str, Any]:
    return {"fp": f"{title}:{uuid.uuid7()}", "title": title, "ts": when or clock.now()}
