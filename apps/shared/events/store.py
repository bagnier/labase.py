"""The business-events write path (``emit``) and the timeline projection.

``emit`` records every emitted ``BusinessEvent`` to the append-only trail: this module maps an event
onto row columns (:func:`_event_columns`) and persists it via the
:class:`~apps.shared.events.repository.EventRepository` — on the request's own unit of work
(:func:`persist_fact`), so the fact commits iff the action commits (atomic). Only the fallback path
(no ambient session: auth signals, seeders) stays best-effort on a detached admin session.

The rest of the module is pure presentation: :func:`activity_entries` and the contribution-calendar
helpers render a scoped, payload-free timeline from rows the repository reads — the raw
``kind``/payload never reach a member.
"""

import asyncio
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import get_contextvars

from apps.shared import clock
from apps.shared.events.repository import BusinessEventRow, EventRepository
from apps.shared.events.types import BusinessEvent
from apps.shared.persistence.database import admin_session_factory

log = structlog.get_logger("labase.business_events")


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
        """Persist the row on ``s`` with the actor handle denormalized; the caller commits."""
        repo = EventRepository(s)
        stored = dict(payload) if payload else {}
        handle = await repo.actor_handle(user_id)
        if handle:
            stored["actor"] = handle  # denormalized 'who' — RLS hides co-members' profiles
        await repo.save(
            kind=kind,
            level=level,
            icon=icon,
            user_id=user_id,
            ip=ip,
            org_id=org_id,
            entity_id=entity_id,
            request_id=request_id,
            payload=stored or None,
        )

    if session is not None:
        await write(session)
        return
    try:
        async with admin_session_factory()() as own:
            await write(own)
            await own.commit()
    except Exception:
        log.warning("business_event.write_failed", kind=kind, user_id=user_id)


# Field-name substrings that must never reach the persisted payload verbatim (e.g.
# ``UserCreated.access_token``). Matched case-insensitively against each field's name.
_REDACT_SUBSTRINGS = ("token", "password", "secret")


def _loggable_payload(event: BusinessEvent) -> dict[str, Any]:
    """The event's instance fields as a plain dict, with secret-named fields redacted — one place
    decides what of an event is safe to serialize into the trail's ``payload``."""
    if not is_dataclass(event) or isinstance(event, type):
        return {}
    payload: dict[str, Any] = {}
    for f in fields(event):
        value = getattr(event, f.name)
        if any(s in f.name.lower() for s in _REDACT_SUBSTRINGS):
            payload[f.name] = "***" if value is not None else None
        else:
            payload[f.name] = value
    return payload


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


def _activity_label(kind: str) -> str:
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
                "label": _activity_label(r.kind),
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
