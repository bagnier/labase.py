"""The activity projection — pure presentation over journal records.

The repository reads the journal; this module humanizes those records for the two surfaces that
show a member their own history: the profile / dashboard feed, and the contribution calendar.
Every function is pure — no session, no I/O — and the raw ``kind``/payload never reach a member;
only projected, safe fields do.

Not :mod:`apps.timeline`, which is the console's unified read view over the firehose, the journal
*and* issue occurrences. This one owns no screen, reads one source, and knows nothing of the bus,
the catalog, the wiring or the listener — only :class:`BusinessEventRecord`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import groupby

from apps.shared.events.models import BusinessEventRecord

# ── Activity feed — humanize records for the profile/dashboard timeline ──────────────────────────


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    """One humanized journal record for the timeline — *who did what to which, when*. Only safe,
    projected fields; the raw ``kind`` and the rest of the payload never reach here. Templates
    read it by attribute (``e.who``, ``e.icon``)."""

    who: str | None  # the actor's handle, or None on the viewer's own journal
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
    string-shaping: shared never enumerates the apps, it just humanizes the verb a record
    carries."""
    return verb.replace("_", " ").capitalize()


def activity_entries(
    records: list[BusinessEventRecord],
    *,
    show_actor: bool = True,
    link: Callable[[BusinessEventRecord], str | None] | None = None,
) -> list[ActivityEntry]:
    """Project records to *who did what to which, when* — only safe fields, never the raw
    ``kind`` or the rest of the payload. ``show_actor`` drops *who* on the profile's own journal
    (always the viewer); ``link`` lets the surface supply a deep link."""
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
        for r in records
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


def _calendar_window(
    today: date, since: date | None, min_weeks: int, max_weeks: int
) -> tuple[list[date], str]:
    """The Monday-starting week columns to render, and the label naming that range.

    The window runs from the join week (``since``) to now, floored at ``min_weeks`` (a fresh
    account isn't a lone column) and capped at ``max_weeks`` (so a new account never shows a
    mostly-empty year). A window that hit the cap can no longer claim the join date, so it says
    "last 12 months" instead."""
    end_monday = today - timedelta(days=today.weekday())
    if since is not None:
        since_monday = since - timedelta(days=since.weekday())
        weeks_needed = (end_monday - since_monday).days // 7 + 1
    else:
        weeks_needed = max_weeks
    weeks = max(min_weeks, min(max_weeks, weeks_needed))
    label = (
        "Last 12 months"
        if since is None or weeks_needed > max_weeks
        else f"Since {since.strftime('%b %Y')}"
    )
    start = end_monday - timedelta(weeks=weeks - 1)
    return [start + timedelta(weeks=w) for w in range(weeks)], label


def _intensity(counts: dict[date, int]) -> Callable[[int], int]:
    """The 0–4 ``level`` ramp, built from quartiles of the non-zero days — so it adapts to each
    user instead of a fixed scale that washes out a light one. With no activity at all, every
    non-zero day is a plain level 1."""
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

    return level


def _week_column(
    week_start: date, today: date, counts: dict[date, int], level: Callable[[int], int]
) -> HeatmapWeek:
    """One column of the grid, Mon→Sun (``week_start`` is a Monday). A day past today is a blank
    filler cell, not a zero-activity one."""
    days: list[HeatmapDay] = []
    for offset in range(7):
        d = week_start + timedelta(days=offset)
        if d > today:
            days.append(HeatmapDay(empty=True))
            continue
        n = counts.get(d, 0)
        moment = d.strftime("%b %-d, %Y")
        title = (
            f"{n} action{'s' if n != 1 else ''} on {moment}" if n else f"No activity on {moment}"
        )
        days.append(HeatmapDay(level=level(n), title=title))
    return HeatmapWeek(days=days)


def _month_headers(week_starts: list[date]) -> list[MonthHeader]:
    """Colspan segments over the consecutive week-columns sharing a month, so a label never widens
    a cell. A segment narrower than 3 weeks stays blank to avoid clutter."""
    headers: list[MonthHeader] = []
    for _key, run in groupby(week_starts, key=lambda ws: (ws.year, ws.month)):
        cols = list(run)
        span = len(cols)
        headers.append(MonthHeader(label=cols[0].strftime("%b") if span >= 3 else "", span=span))
    return headers


def heatmap_calendar(
    counts: dict[date, int],
    *,
    now: datetime,
    since: date | datetime | None = None,
    min_weeks: int = 5,
    max_weeks: int = 53,
) -> HeatmapCalendar:
    """A GitHub-style contribution grid, fully computed for the macro to iterate — the window
    (:func:`_calendar_window`), the intensity ramp (:func:`_intensity`) and the month segments
    (:func:`_month_headers`) each decided on their own."""
    today = now.date()
    since_date = since.date() if isinstance(since, datetime) else since
    week_starts, range_label = _calendar_window(today, since_date, min_weeks, max_weeks)
    level = _intensity(counts)
    return HeatmapCalendar(
        weeks=[_week_column(ws, today, counts, level) for ws in week_starts],
        weekday_labels=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        month_headers=_month_headers(week_starts),
        range_label=range_label,
    )
