"""The business-events store — the append-only trail every domain event is persisted to.

The producer is the typed event bus (:mod:`apps.shared.events`): :func:`~apps.shared.bus.EventBus`
``emit`` records every emitted ``BusinessEvent`` here. The store is member-readable (RLS scopes rows
to the reader), so the profile and org-dashboard timelines read it on the user's own session; the
admin console reads it all through the BYPASSRLS session.

Transactional by doctrine: the fact is written on the request's own unit of work
(:func:`persist_fact`), so it commits iff the action commits (atomic) — a failed write rolls the
mutation back. Only the fallback path (no ambient session: auth signals, seeders) stays best-effort.
Presentation helpers (:func:`activity_entries`) render a scoped, payload-free timeline; the raw
``kind``/payload never reach a member.
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import BigInteger, Date, DateTime, Text, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from structlog.contextvars import get_contextvars

from apps.shared import clock
from apps.shared.events import BusinessEvent, _loggable_payload
from apps.shared.persistence.base import Base
from apps.shared.persistence.database import admin_session_factory

log = structlog.get_logger("labase.business_events")


class BusinessEventLog(Base):
    """The append-only business-event row. Members read their own/their orgs' rows via RLS;
    only the persister's BYPASSRLS admin session writes (no insert grant to authenticated)."""

    __tablename__ = "business_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )
    level: Mapped[str]
    kind: Mapped[str]
    icon: Mapped[str | None] = mapped_column(default=None)
    user_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    ip: Mapped[str | None] = mapped_column(default=None)
    org_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    entity_id: Mapped[str | None] = mapped_column(default=None)
    request_id: Mapped[str | None] = mapped_column(default=None)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)


@dataclass(frozen=True)
class BusinessEventRow:
    """A read of the business-events trail, flattened for the unified timeline."""

    ts: datetime
    level: str
    kind: str
    icon: str | None
    org_id: str | None
    user_id: str | None
    entity_id: str | None
    request_id: str | None
    payload: dict[str, Any]


async def search_business_events(
    session: AsyncSession,
    *,
    level: str | None = None,
    org_id: str | None = None,
    user_id: str | None = None,
    entity_id: str | None = None,
    request_id: str | None = None,
    app: str | None = None,
    text: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[BusinessEventRow]:
    """Newest-first, bounded read of the trail under the given filters.

    RLS scopes the rows to the session's reader (self + org memberships); admin sessions see
    all. Callers still pass ``user_id=`` / ``org_id=`` to narrow to one feed. ``app`` matches the
    ``kind`` prefix (``"todo"`` → ``todo.*``); ``offset`` pages a fixed ``limit`` window."""
    query = (
        select(BusinessEventLog).order_by(BusinessEventLog.id.desc()).limit(limit).offset(offset)
    )
    if level:
        query = query.where(BusinessEventLog.level == level)
    if org_id:
        query = query.where(BusinessEventLog.org_id == uuid.UUID(org_id))
    if user_id:
        query = query.where(BusinessEventLog.user_id == uuid.UUID(user_id))
    if entity_id:
        query = query.where(BusinessEventLog.entity_id == entity_id)
    if request_id:
        query = query.where(BusinessEventLog.request_id == request_id)
    if app:
        query = query.where(BusinessEventLog.kind.like(f"{app}.%"))
    if text:
        like = f"%{text}%"
        query = query.where(
            or_(BusinessEventLog.kind.ilike(like), cast(BusinessEventLog.payload, Text).ilike(like))
        )
    if from_dt:
        query = query.where(BusinessEventLog.created_at >= from_dt)
    if to_dt:
        query = query.where(BusinessEventLog.created_at <= to_dt)
    rows = await session.scalars(query)
    return [
        BusinessEventRow(
            ts=r.created_at,
            level=r.level,
            kind=r.kind,
            icon=r.icon,
            org_id=str(r.org_id) if r.org_id else None,
            user_id=str(r.user_id) if r.user_id else None,
            entity_id=r.entity_id,
            request_id=r.request_id,
            payload=r.payload or {},
        )
        for r in rows
    ]


async def _actor_handle(session: AsyncSession, user_id: str | None) -> str | None:
    """Resolve the actor's handle, to denormalize into the event so the feed can show *who* acted.
    Runs on the persister's admin session: profiles are ``own read`` under RLS, so a member could
    never resolve a co-member at read time — storing it at write time keeps 'who' visible to every
    viewer, and pins the handle the actor bore at the moment of the action."""
    if not user_id:
        return None
    try:
        return await session.scalar(
            text("select handle from profiles where auth_user_id = :id"),
            {"id": uuid.UUID(user_id)},  # bind as uuid, not text, so the column compare holds
        )
    except Exception:
        return None


async def insert_business_event(
    *,
    session: AsyncSession | None = None,
    kind: str,
    level: str,
    icon: str | None = None,
    user_id: str | None,
    ip: str | None,
    org_id: str | None,
    entity_id: str | None = None,
    request_id: str | None,
    payload: dict[str, Any] | None,
) -> None:
    """Write one business-events row.

    With ``session`` (a request's unit of work), the row rides that transaction — it commits iff the
    action commits, and a failure propagates (atomic). Without one, a **best-effort** admin write on
    a fresh session that swallows failures (auth signals, seeders, non-request contexts)."""

    async def write(s: AsyncSession) -> None:
        """Add + flush the row on ``s`` with the actor handle denormalized; the caller commits."""
        stored = dict(payload) if payload else {}
        handle = await _actor_handle(s, user_id)
        if handle:
            stored["actor"] = handle  # denormalized 'who' — RLS hides co-members' profiles
        s.add(
            BusinessEventLog(
                kind=kind,
                level=level,
                icon=icon,
                user_id=uuid.UUID(user_id) if user_id else None,
                ip=ip,
                org_id=uuid.UUID(org_id) if org_id else None,
                entity_id=entity_id,
                request_id=request_id,
                payload=stored or None,
            )
        )
        await s.flush()  # surface RLS/constraint errors now, within the caller's transaction

    if session is not None:
        await write(session)
        return
    try:
        async with admin_session_factory()() as own:
            await write(own)
            await own.commit()
    except Exception:
        log.warning("business_event.write_failed", kind=kind, user_id=user_id)


def _event_columns(event: BusinessEvent) -> dict[str, Any]:
    """Map a ``BusinessEvent`` onto the ``business_events`` row fields — scoping lifted to their own
    columns, the rest to ``payload``, ``ip``/``request_id`` read from the request contextvars."""
    ctx = get_contextvars()
    payload = _loggable_payload(event)
    payload.pop("actor_id", None)
    payload.pop("org_id", None)
    payload.pop("entity_id", None)  # promoted to its own column, like actor_id/org_id
    return dict(
        kind=event.kind,
        level=event.level,
        icon=event.icon,
        user_id=event.actor_id,
        ip=ctx.get("ip"),
        org_id=event.org_id,
        entity_id=event.entity_id,
        request_id=ctx.get("request_id"),
        payload=payload or None,
    )


async def persist_fact(event: BusinessEvent, session: AsyncSession | None) -> None:
    """``emit``'s persist path.

    With an ambient request session, the fact is written on it — atomic with the action (commits
    iff the mutation commits). With none (auth signals, non-request contexts) there is no
    transaction to join, so it is a best-effort detached write off the critical path — never
    blocking or failing the caller."""
    columns = _event_columns(event)
    if session is not None:
        await insert_business_event(session=session, **columns)
    else:
        asyncio.create_task(insert_business_event(**columns))


# ── Presentation — humanize rows for the profile/dashboard timeline ──────────────────────────

_FALLBACK_ICON = "circle"  # for legacy rows written before events carried an icon


def activity_label(kind: str) -> str:
    """`auth.oauth_signed_in` → `Oauth signed in` — readable without a per-event table. Purely
    string-shaping: shared never enumerates the apps, it just humanizes whatever kind it's given."""
    return kind.split(".", 1)[-1].replace("_", " ").capitalize()


def _ago(ts: datetime, now: datetime) -> str:
    """A compact relative moment (`3h ago`, `2d ago`, `Mar 4`) — an activity feed reads better in
    elapsed time than in wall-clock; the exact instant stays on the row's ``title``/``datetime``."""
    secs = max(0.0, (now - ts).total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    if secs < 604800:
        return f"{int(secs // 86400)}d ago"
    return ts.strftime("%b %-d")


def activity_entries(
    rows: list[BusinessEventRow],
    *,
    show_actor: bool = True,
    link: Callable[[BusinessEventRow], str | None] | None = None,
) -> list[dict[str, Any]]:
    """Humanize rows for the activity feed — *who did what to which document, when*:

    - ``who``    the actor's handle (denormalized into the payload at write time); dropped when
                 ``show_actor`` is off, as on the profile's own trail where it's always the viewer.
    - ``label``  the verb (``created``/``ticked``/``member joined``…), humanized from the kind.
    - ``detail`` the object's own name (the todo title, the page, the file) — the *which*.
    - ``icon`` / ``level``  the event's phosphor glyph and severity (colours the node).
    - ``ts`` / ``ago``  the absolute instant (for ``time``) and a compact relative moment.
    - ``href``   an optional deep link the surface supplies via ``link`` (the entity's page, the
                 filtered logs…) — the timeline renders the row as a link when present.

    Never the raw ``kind`` or the rest of the payload — only these projected, safe fields."""
    now = clock.now()
    entries = []
    for r in rows:
        payload = r.payload or {}
        entries.append(
            {
                "who": payload.get("actor") if show_actor else None,
                "label": activity_label(r.kind),
                "detail": payload.get("label"),
                "app": r.kind.split(".", 1)[0],
                "icon": r.icon or _FALLBACK_ICON,
                "level": r.level,
                "ts": r.ts,
                "ago": _ago(r.ts, now),
                "href": link(r) if link else None,
            }
        )
    return entries


def group_activity_by_day(entries: list[dict[str, Any]], *, now: datetime) -> list[dict[str, Any]]:
    """Group already-humanized entries (newest-first) into day sections for the feed —
    ``Today`` / ``Yesterday`` / ``Mon, Jul 13`` — each carrying its own count."""
    today = now.date()
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for e in entries:
        d = e["ts"].date()
        if current is None or current["date"] != d:
            if d == today:
                label = "Today"
            elif d == today - timedelta(days=1):
                label = "Yesterday"
            else:
                label = e["ts"].strftime("%a, %b %-d")
            current = {"date": d, "label": label, "entries": []}
            groups.append(current)
        current["entries"].append(e)
    for g in groups:
        g["count"] = len(g["entries"])
    return groups


# ── Contribution calendar & headline stats ──────────────────────────────────────────────────


async def daily_activity_counts(
    session: AsyncSession,
    *,
    user_id: str | None = None,
    org_id: str | None = None,
    days: int = 366,
) -> dict[date, int]:
    """Per-day counts of the trail over a trailing window, for the contribution calendar.

    RLS-scoped like :func:`search_business_events`; callers narrow to one feed with
    ``user_id`` / ``org_id``. Grouped by calendar day (DB timezone). Missing days simply don't
    appear — the calendar builder fills the gaps."""
    since = clock.now() - timedelta(days=days)
    day = cast(BusinessEventLog.created_at, Date)
    query = select(day, func.count()).where(BusinessEventLog.created_at >= since).group_by(day)
    if user_id:
        query = query.where(BusinessEventLog.user_id == uuid.UUID(user_id))
    if org_id:
        query = query.where(BusinessEventLog.org_id == uuid.UUID(org_id))
    rows = await session.execute(query)
    return {d: n for d, n in rows.all()}


def activity_stats(counts: dict[date, int], *, now: datetime) -> dict[str, int]:
    """Headline numbers for the activity view, derived from per-day counts (pure).

    ``total`` over the window, ``active_days`` with any action, the ``longest_streak`` of
    consecutive active days, ``this_week`` (trailing 7 days) and its ``week_delta`` vs the 7
    days before."""
    today = now.date()
    total = sum(counts.values())
    active_days = sum(1 for n in counts.values() if n)
    active = sorted(d for d, n in counts.items() if n)
    longest = streak = 0
    prev: date | None = None
    for d in active:
        streak = streak + 1 if prev is not None and (d - prev).days == 1 else 1
        longest = max(longest, streak)
        prev = d
    this_week = sum(counts.get(today - timedelta(days=i), 0) for i in range(7))
    last_week = sum(counts.get(today - timedelta(days=i), 0) for i in range(7, 14))
    return {
        "total": total,
        "active_days": active_days,
        "longest_streak": longest,
        "this_week": this_week,
        "week_delta": this_week - last_week,
    }


def heatmap_calendar(
    counts: dict[date, int],
    *,
    now: datetime,
    since: date | datetime | None = None,
    min_weeks: int = 5,
    max_weeks: int = 53,
) -> dict[str, Any]:
    """A GitHub-style contribution grid, fully computed for the macro to iterate.

    Columns are ISO weeks (Mon–Sun), oldest→newest; cells past today are ``empty``. Intensity
    is a 0–4 ``level`` from quartiles of the non-zero days, so the ramp adapts to each user
    instead of a fixed scale that would wash out a light one.

    The window spans the member's history: from the week they joined (``since``) to now, floored
    at ``min_weeks`` (~a month, so a fresh account isn't a lone column) and capped at ``max_weeks``
    (a year). ``range_label`` names it — ``Since Jun 2026`` while short, ``Last 12 months`` once
    capped — so a new account never shows a mostly-empty year."""
    today = now.date()
    end_monday = today - timedelta(days=today.weekday())
    since_date = since.date() if isinstance(since, datetime) else since
    if since_date is not None:
        since_monday = since_date - timedelta(days=since_date.weekday())
        weeks_needed = (end_monday - since_monday).days // 7 + 1
    else:
        weeks_needed = max_weeks
    weeks = max(min_weeks, min(max_weeks, weeks_needed))
    capped = weeks_needed > max_weeks or since_date is None
    range_label = "Last 12 months" if capped else f"Since {since_date.strftime('%b %Y')}"
    start = end_monday - timedelta(weeks=weeks - 1)
    nonzero = sorted(n for n in counts.values() if n)
    thresholds = (
        [nonzero[min(len(nonzero) - 1, int(len(nonzero) * f))] for f in (0.25, 0.5, 0.75)]
        if nonzero
        else []
    )

    def level(n: int) -> int:
        if n <= 0:
            return 0
        if not thresholds:
            return 1
        t1, t2, t3 = thresholds
        return 1 if n <= t1 else 2 if n <= t2 else 3 if n <= t3 else 4

    weeks_out: list[dict[str, Any]] = []
    week_starts = [start + timedelta(weeks=w) for w in range(weeks)]
    for week_start in week_starts:
        days: list[dict[str, Any]] = []
        for i in range(7):
            d = week_start + timedelta(days=i)
            if d > today:
                days.append({"empty": True})
                continue
            n = counts.get(d, 0)
            moment = d.strftime("%b %-d, %Y")
            title = (
                f"{n} action{'s' if n != 1 else ''} on {moment}"
                if n
                else f"No activity on {moment}"
            )
            days.append({"level": level(n), "count": n, "title": title})
        weeks_out.append({"days": days})

    # Month headers as colspan segments (grouped consecutive week-columns sharing a month), so
    # the label never widens a cell. A segment narrower than 3 weeks stays blank to avoid clutter.
    headers: list[dict[str, Any]] = []
    for week_start in week_starts:
        key = (week_start.year, week_start.month)
        if headers and headers[-1]["key"] == key:
            headers[-1]["span"] += 1
        else:
            headers.append({"key": key, "span": 1, "abbr": week_start.strftime("%b")})
    month_headers = [
        {"label": h["abbr"] if h["span"] >= 3 else "", "span": h["span"]} for h in headers
    ]

    # rows are Mon→Sun (week_start is a Monday); every weekday labelled.
    return {
        "weeks": weeks_out,
        "weekday_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "month_headers": month_headers,
        "range_label": range_label,
    }
