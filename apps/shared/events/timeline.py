"""The business-events timeline projection — pure presentation over trail rows.

The repository reads the trail; this module humanizes those rows for the surfaces that show history
(profile / dashboard feed, contribution calendar). Every function is pure — no session, no I/O — and
the raw ``kind``/payload never reach a member; only projected, safe fields do.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import groupby

from apps.shared.events.models import BusinessEventRecord

# ── Activity feed — humanize rows for the profile/dashboard timeline ──────────────────────────


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    """One humanized trail row for the timeline — *who did what to which, when*. Only safe,
    projected fields; the raw ``kind`` and the rest of the payload never reach here. Templates
    read it by attribute (``e.who``, ``e.icon``)."""

    who: str | None  # the actor's handle, or None on the viewer's own trail
    label: str  # the humanized verb (``Created``), never the dotted kind
    detail: str | None  # the subject's own name (a todo title, a page slug)
    app: str  # the owning app prefix, for a subtle source line
    icon: str  # the phosphor name the event owns
    ts: datetime  # the exact instant, shown as clock time under the day header
    href: str | None  # a deep link to the concerned entity, when the surface supplies one


@dataclass(frozen=True, slots=True)
class DaySection:
    """A day's worth of feed entries under a ``Today`` / ``Yesterday`` / ``Mon, Jul 13`` header."""

    date: date
    label: str
    entries: list[ActivityEntry]

    @property
    def count(self) -> int:
        return len(self.entries)


def _activity_label(verb: str) -> str:
    """`share_link_created` → `Share link created` — readable without a per-event table. Purely
    string-shaping: shared never enumerates the apps, it just humanizes the verb the row carries."""
    return verb.replace("_", " ").capitalize()


def activity_entries(
    rows: list[BusinessEventRecord],
    *,
    show_actor: bool = True,
    link: Callable[[BusinessEventRecord], str | None] | None = None,
) -> list[ActivityEntry]:
    """Project rows to *who did what to which, when* — only safe fields, never the raw ``kind`` or
    the rest of the payload. ``show_actor`` drops *who* on the profile's own trail (always the
    viewer); ``link`` lets the surface supply a deep link."""
    return [
        ActivityEntry(
            who=r.user_name if show_actor else None,
            label=_activity_label(r.verb),
            detail=r.entity_name,
            app=r.app_name,
            icon=r.icon,  # not-null default 'circle' since 20260726000002 — always set
            ts=r.created_at,
            href=link(r) if link else None,
        )
        for r in rows
    ]


def _day_label(d: date, today: date) -> str:
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    return d.strftime("%a, %b %-d")


def group_activity_by_day(entries: list[ActivityEntry], *, now: datetime) -> list[DaySection]:
    """Group humanized entries (newest-first) into ``Today`` / ``Yesterday`` / ``Mon, Jul 13``
    day sections, each carrying its count."""
    today = now.date()
    sections: list[DaySection] = []
    for entry in entries:
        d = entry.ts.date()
        if not sections or sections[-1].date != d:
            sections.append(DaySection(date=d, label=_day_label(d, today), entries=[]))
        sections[-1].entries.append(entry)
    return sections


# ── Contribution calendar & headline stats ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ActivityStats:
    """Headline numbers for the activity view, computed from per-day counts."""

    total: int
    active_days: int
    longest_streak: int  # longest run of consecutive active days
    this_week: int
    week_delta: int  # this week minus the one before


@dataclass(frozen=True, slots=True)
class HeatmapDay:
    """One cell in the contribution grid — a real day (its ``level``/``count``/``title``) or an
    out-of-range filler (``empty``) that renders as a blank cell."""

    empty: bool = False
    level: int = 0  # 0–4 intensity, from quartiles of the non-zero days
    title: str = ""  # the cell's accessible label / tooltip (carries the day's count)


@dataclass(frozen=True, slots=True)
class HeatmapWeek:
    """A column of the grid — seven ``HeatmapDay`` cells, Mon→Sun."""

    days: list[HeatmapDay]


@dataclass(frozen=True, slots=True)
class MonthHeader:
    """A colspan segment over the week-columns of one month; ``label`` is blank for a short run
    (fewer than three weeks) so it never widens a cell."""

    label: str
    span: int


@dataclass(frozen=True, slots=True)
class HeatmapCalendar:
    """A GitHub-style contribution grid, fully computed for the macro to iterate."""

    weeks: list[HeatmapWeek]
    weekday_labels: list[str]
    month_headers: list[MonthHeader]
    range_label: str


def activity_stats(counts: dict[date, int], *, now: datetime) -> ActivityStats:
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
    return ActivityStats(
        total=total,
        active_days=active_days,
        longest_streak=longest,
        this_week=this_week,
        week_delta=this_week - last_week,
    )


def heatmap_calendar(
    counts: dict[date, int],
    *,
    now: datetime,
    since: date | datetime | None = None,
    min_weeks: int = 5,
    max_weeks: int = 53,
) -> HeatmapCalendar:
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

    week_starts = [start + timedelta(weeks=w) for w in range(weeks)]
    weeks_out: list[HeatmapWeek] = []
    for week_start in week_starts:
        days: list[HeatmapDay] = []
        for i in range(7):
            d = week_start + timedelta(days=i)
            if d > today:
                days.append(HeatmapDay(empty=True))
                continue
            n = counts.get(d, 0)
            moment = d.strftime("%b %-d, %Y")
            title = (
                f"{n} action{'s' if n != 1 else ''} on {moment}"
                if n
                else f"No activity on {moment}"
            )
            days.append(HeatmapDay(level=level(n), title=title))
        weeks_out.append(HeatmapWeek(days=days))

    # Month headers as colspan segments (consecutive week-columns sharing a month), so the label
    # never widens a cell. A segment narrower than 3 weeks stays blank to avoid clutter.
    month_headers: list[MonthHeader] = []
    for _key, run in groupby(week_starts, key=lambda ws: (ws.year, ws.month)):
        cols = list(run)
        span = len(cols)
        month_headers.append(
            MonthHeader(label=cols[0].strftime("%b") if span >= 3 else "", span=span)
        )

    # rows are Mon→Sun (week_start is a Monday); every weekday labelled.
    return HeatmapCalendar(
        weeks=weeks_out,
        weekday_labels=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        month_headers=month_headers,
        range_label=range_label,
    )
