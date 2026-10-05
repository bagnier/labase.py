"""Journal records made readable for a member: the profile/dashboard feed and the contribution
calendar. Pure functions over :class:`BusinessEventRecord`; the raw ``kind`` and payload never
reach the page. The console's view of the journal is :mod:`apps.timeline`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import groupby
from typing import Any

from pydantic import BaseModel

from apps.shared.events.models import BusinessEventRecord
from apps.shared.vocabulary import AppName, PhosphorIcon

# ── Activity feed — humanize records for the profile/dashboard timeline ──────────────────────────


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    """One feed line: who did what to which, when."""

    who: str | None  # pinned handle or email; None on the viewer's own journal
    label: str  # the humanized verb, ``Created``
    detail: str | None  # the subject's name (a todo title, a page slug)
    app: AppName
    icon: PhosphorIcon
    ts: datetime
    href: str | None


@dataclass(frozen=True, slots=True)
class DaySection:
    """Feed entries under a ``Today`` / ``Yesterday`` / ``Mon, Jul 13`` header."""

    date: date
    label: str
    entries: list[ActivityEntry]

    @property
    def count(self) -> int:
        return len(self.entries)


def _activity_label(verb: str) -> str:
    """`share_link_created` → `Share link created`, with no per-event table to maintain."""
    return verb.replace("_", " ").capitalize()


def activity_entries(
    records: list[BusinessEventRecord],
    *,
    show_actor: bool = True,
    link: Callable[[BusinessEventRecord], str | None] | None = None,
) -> list[ActivityEntry]:
    """``show_actor=False`` on the viewer's own journal; ``link`` builds each entry's deep link."""
    return [
        ActivityEntry(
            who=r.user_name if show_actor else None,
            label=_activity_label(r.verb),
            detail=r.entity_name,
            app=r.app_name,
            icon=r.icon,
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
    """Split newest-first entries into day sections."""
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
    total: int
    active_days: int
    longest_streak: int  # consecutive active days
    this_week: int
    week_delta: int  # this week minus the one before


@dataclass(frozen=True, slots=True)
class HeatmapDay:
    """A grid cell: a day, or a blank filler (``empty``) past today."""

    empty: bool = False
    level: int = 0  # 0–4, see ``_intensity``
    title: str = ""  # accessible label and tooltip


@dataclass(frozen=True, slots=True)
class HeatmapWeek:
    """Seven cells, Mon→Sun."""

    days: list[HeatmapDay]


@dataclass(frozen=True, slots=True)
class MonthHeader:
    """A month label spanning its week columns."""

    label: str
    span: int


@dataclass(frozen=True, slots=True)
class HeatmapCalendar:
    """A GitHub-style contribution grid, ready for the template macro to iterate."""

    weeks: list[HeatmapWeek]
    weekday_labels: list[str]
    month_headers: list[MonthHeader]
    range_label: str


def activity_stats(counts: dict[date, int], *, now: datetime) -> ActivityStats:
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
    """The week columns (their Mondays) from the join week to now, kept between ``min_weeks``
    and ``max_weeks``, and the range's label: a capped window cannot say "Since <join date>"."""
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
    """The 0–4 level from quartiles of the active days, so a light user's grid is not washed out
    by a fixed scale."""
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
    """One segment per month; under three weeks it stays unlabelled so the label never widens a
    cell."""
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
    """The contribution grid from per-day counts, starting at the join date ``since``."""
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


class ActivityFeedRead(BaseModel):
    """The feed for a JSON caller, ``ts`` in ISO."""

    entries: list[dict[str, Any]]
