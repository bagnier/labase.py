"""The business-events timeline projection — pure presentation over trail rows.

The repository reads the trail; this module humanizes those rows for the surfaces that show history
(profile / dashboard feed, contribution calendar). Every function is pure — no session, no I/O — and
the raw ``kind``/payload never reach a member; only projected, safe fields do.
"""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from apps.shared import clock
from apps.shared.events.models import BusinessEventRow

# ── Activity feed — humanize rows for the profile/dashboard timeline ──────────────────────────

_FALLBACK_ICON = "circle"  # for legacy rows written before events carried an icon


def _activity_label(kind: str) -> str:
    """`auth.oauth_signed_in` → `Oauth signed in` — readable without a per-event table. Purely
    string-shaping: shared never enumerates the apps, it just humanizes whatever kind it's given."""
    return kind.split(".", 1)[-1].replace("_", " ").capitalize()


def ago(ts: datetime, now: datetime) -> str:
    """A compact relative moment (`3h ago`, `Mar 4`) — a feed reads better in elapsed time; the
    exact instant stays on the row's ``title``/``datetime``."""
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
    """Project rows to *who did what to which, when* — only safe fields, never the raw ``kind`` or
    the rest of the payload. ``show_actor`` drops *who* on the profile's own trail (always the
    viewer); ``link`` lets the surface supply a deep link."""
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
                "ago": ago(r.ts, now),
                "href": link(r) if link else None,
            }
        )
    return entries


def group_activity_by_day(entries: list[dict[str, Any]], *, now: datetime) -> list[dict[str, Any]]:
    """Group humanized entries (newest-first) into ``Today`` / ``Yesterday`` / ``Mon, Jul 13``
    day sections, each with its count."""
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
    """Headline numbers for the activity view, from per-day counts — totals, active days, the
    longest consecutive-day streak, and this week vs the one before."""
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

    Intensity is a 0–4 ``level`` from quartiles of the non-zero days, so the ramp adapts to each
    user instead of a fixed scale that washes out a light one. The window runs from the join week
    (``since``) to now, floored at ``min_weeks`` (a fresh account isn't a lone column) and capped at
    ``max_weeks`` (so a new account never shows a mostly-empty year)."""
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
