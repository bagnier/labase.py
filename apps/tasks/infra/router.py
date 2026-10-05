"""The Tasks screen: the backlog (what the queue still owes, parked first) and the history (a
film strip of what it ran, failed tries read from the log sink). Not a bug tracker: a hundred tasks
failing alike are one issue, still a hundred rows owed.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.shared import clock
from apps.shared.http import json_and_html, wants_full_page, wants_json
from apps.shared.http.templates import templates
from apps.shared.integration.fullpage import fullpage_context
from apps.shared.logs.repository import LogRepository
from apps.shared.persistence.database import AdminSession
from apps.shared.queue import (
    TASK_STATES,
    RecurringTopic,
    TaskBucket,
    bucketed_runs,
    count_unfinished_tasks,
    list_unfinished_tasks,
    live_recurring_topics,
    unfinished_task_topics,
)
from apps.tasks.domain.screen import TasksPage
from apps.tasks.domain.strip import (
    BANDS,
    StripLane,
    axis_ticks,
    bucket_blocks,
    bucket_seconds,
    spell_cadence,
    spell_duration,
    spell_tally,
    tally_bar,
    topic_label,
)

router = APIRouter(tags=["tasks"])


_HISTORY_WINDOW = timedelta(hours=6)
# The lines a failed try writes; a success writes none.
_ATTEMPT_LINES = ("queue.task_retrying", "queue.task_failed")


def _window_bound(value: str) -> datetime | None:
    """A ``datetime-local`` value as UTC, like the whole console; empty is ``None``."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


def _history_window(from_dt: str, to_dt: str) -> tuple[datetime, datetime]:
    end = _window_bound(to_dt) or clock.now()
    start = _window_bound(from_dt) or end - _HISTORY_WINDOW
    return (start, end) if start < end else (end - _HISTORY_WINDOW, end)


def _lanes(
    counted: list[TaskBucket],
    attempts: dict[tuple[str, datetime], int],
    bucket: int,
    start: datetime,
    end: datetime,
) -> list[StripLane]:
    """One lane per topic, one block per slot; the caller fills the margins."""
    by_topic: dict[str, dict[datetime, dict[str, int]]] = {}
    for one in counted:
        by_topic.setdefault(one.topic, {}).setdefault(one.slot, {})[one.state] = one.runs
    # Failed tries without a queue row yet: a task still going wrong, drawn all the same.
    for topic, slot in attempts:
        by_topic.setdefault(topic, {}).setdefault(slot, {})

    lanes = []
    for topic, slots in sorted(by_topic.items()):
        blocks = [
            block
            for slot, counts in sorted(slots.items())
            for block in bucket_blocks(
                slot_start=slot,
                slot_end=slot + timedelta(seconds=bucket),
                topic=topic,
                counts=counts,
                attempts=attempts.get((topic, slot), 0),
                window_start=start,
                window_end=end,
            )
        ]
        totals = list(slots.values())
        tally: dict[str, int] = {}
        for slot_counts in totals:
            for state, n in slot_counts.items():
                tally[state] = tally.get(state, 0) + n
        # Counted like the blocks, so margin and film agree.
        failed = sum(attempts.get((topic, slot), 0) for slot in slots)
        lanes.append(
            StripLane(
                topic=topic,
                label=topic_label(topic),
                cadence="",
                state="parked" if any("parked" in c for c in totals) else "done",
                counts=tally | ({"attempt": failed} if failed else {}),
                segments=blocks,
            )
        )
    return lanes


def _clock_of(topic: RecurringTopic | None) -> str:
    """Cadence and next run; empty once the topic has no pending row."""
    return spell_cadence(topic.every_seconds, topic.next_run) if topic else ""


async def _history(session: AdminSession, from_dt: str, to_dt: str) -> dict[str, object]:
    """Recurring lanes above one-shots, all counted in Postgres."""
    start, end = _history_window(from_dt, to_dt)
    bucket = bucket_seconds(start, end)
    cadences = await live_recurring_topics(session)
    attempts = await LogRepository(session).counted_by_payload_key(
        "topic", names=_ATTEMPT_LINES, since=start, until=end, bucket=bucket
    )

    recurring_lanes = [
        replace(lane, cadence=_clock_of(cadences.get(lane.topic)))
        for lane in _lanes(
            await bucketed_runs(session, since=start, until=end, bucket=bucket, recurring=True),
            {k: v for k, v in attempts.items() if k[0] in cadences},
            bucket,
            start,
            end,
        )
    ]
    # Kept even when empty: a missing lane would read as a removed topic.
    drawn = {lane.topic for lane in recurring_lanes}
    recurring_lanes += [
        StripLane(
            topic=t,
            label=topic_label(t),
            cadence=_clock_of(clock_of),
            state="done",
            counts={},
            segments=[],
        )
        for t, clock_of in cadences.items()
        if t not in drawn
    ]
    oneshot_lanes = _lanes(
        await bucketed_runs(session, since=start, until=end, bucket=bucket, recurring=False),
        {k: v for k, v in attempts.items() if k[0] not in cadences},
        bucket,
        start,
        end,
    )
    now = clock.now()
    return {
        "window_start": start,
        "window_end": end,
        "bucket_seconds": bucket,
        "bucket_spelled": spell_duration(bucket),
        "tally_bar": tally_bar,
        "spell_tally": spell_tally,
        # An empty window looks broken, so the screen says why; often local time read as UTC.
        "window_ahead": start > now,
        "has_runs": any(lane.segments for lane in [*recurring_lanes, *oneshot_lanes]),
        "now_utc": now.strftime("%H:%M"),
        "axis": axis_ticks(start, end),
        "bands": BANDS,
        "recurring_lanes": sorted(recurring_lanes, key=lambda lane: lane.topic),
        "oneshot_lanes": oneshot_lanes,
        "from_dt": from_dt,
        "to_dt": to_dt,
    }


@router.get("", responses=json_and_html(TasksPage))
async def get_tasks(
    request: Request,
    current_user: CurrentAdmin,
    session: AdminSession,
    state: str = "",
    topic: str = "",
    from_dt: str = "",
    to_dt: str = "",
    panel: str = "",
) -> Response:
    if state and state not in TASK_STATES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown state")
    tasks = await list_unfinished_tasks(session, state=state, topic=topic)
    counts = await count_unfinished_tasks(session)
    context: dict[str, object] = {
        "tasks": tasks,
        "labels": {t.topic: topic_label(t.topic) for t in tasks},
        # In ``context``: the filter's fragment needs it too.
        "spell_cadence": spell_cadence,
        "state_filter": state,
        "topic_filter": topic,
    }
    if not wants_json(request) and not wants_full_page(request):
        # The form names its panel (empty bounds are ambiguous), and only that panel is swapped:
        # a full reload would land on the default tab.
        if panel == "history":
            return templates.TemplateResponse(
                request, "tasks/_history.html", await _history(session, from_dt, to_dt)
            )
        return templates.TemplateResponse(request, "tasks/_backlog.html", context)
    history = await _history(session, from_dt, to_dt)
    if wants_json(request):
        return JSONResponse(
            {
                "tasks": [t.model_dump(mode="json") for t in tasks],
                "counts": counts,
                "history": _history_json(history),
            }
        )
    return templates.TemplateResponse(
        request,
        "tasks/index.html",
        {
            "user": current_user,
            "counts": counts,
            "panel": panel,
            "states": TASK_STATES,
            "topics": [topic_label(t) for t in await unfinished_task_topics(session)],
            **context,
            **history,
            **await fullpage_context(session, current_user),
        },
    )


def _history_json(history: dict[str, object]) -> dict[str, object]:
    """The lanes as JSON."""
    lanes = [
        {
            "topic": lane.topic,
            "state": lane.state,
            "cadence": lane.cadence,
            "counts": lane.counts,
            "family": family,
            "segments": [
                {
                    "kind": s.kind,
                    "left": s.left,
                    "width": s.width,
                    "starts_at": s.starts_at.isoformat(),
                    "ends_at": s.ends_at.isoformat(),
                }
                for s in lane.segments
            ],
        }
        for family, key in (("recurring", "recurring_lanes"), ("one-shot", "oneshot_lanes"))
        for lane in cast("list[StripLane]", history[key])
    ]
    return {
        "from": cast("datetime", history["window_start"]).isoformat(),
        "to": cast("datetime", history["window_end"]).isoformat(),
        "lanes": lanes,
    }
