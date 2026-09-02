"""The task screen: what the async substrate still owes, and what it ran.

Two readings of one table. The backlog answers *what is owed now* — a row per task the worker has
not finished, parked ones first. The history answers *what happened* — a film strip, one lane per
subject, drawn from the queue for the runs and from the log sink for the failed tries inside them.

An issue and a parked row are not the same object, which is why this is not a second bug tracker:
a hundred tasks failing the same way fold into *one* issue and stay *a hundred* rows of work
nobody did, and marking the issue resolved executes none of them.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.shared import clock
from apps.shared.http import JSON_AND_HTML, wants_full_page, wants_json
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
# The two lines a failed try writes; nothing is logged for a task that simply succeeded.
_ATTEMPT_LINES = ("queue.task_retrying", "queue.task_failed")


def _window_bound(value: str) -> datetime | None:
    """Parse a ``<input type="datetime-local">`` value as UTC; empty means "left alone".

    The console reads and writes UTC throughout (its columns say so), so a bare local-looking
    value is taken at face value rather than guessed at.
    """
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
    """One lane per topic, one block per slot of time — every run in the window, none capped.

    What each lane says in its margins is the caller's: the two families differ only there, and
    threading that difference through here as a pair of callables was more machinery than the
    difference is worth.

    A slot with no queue row but with failed tries logged still gets its block: a task retrying
    across the window has written lines and not yet landed anywhere, and a lane that waited for it
    to finish would show nothing at all while it was going wrong.
    """
    by_topic: dict[str, dict[datetime, dict[str, int]]] = {}
    for one in counted:
        by_topic.setdefault(one.topic, {}).setdefault(one.slot, {})[one.state] = one.runs
    # A slot with tries logged but no queue row is a task still going wrong: it has written lines
    # and landed nowhere, and a lane that waited for it to finish would show nothing meanwhile.
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
        # The failed tries are the log's half of the story, counted the same way the blocks count
        # them — so the margin and the film agree on how many there were.
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
    """How often a recurring topic comes round and when it next does — nothing for a lane whose
    topic no longer has a pending singleton, which is a topic that has stopped recurring."""
    return spell_cadence(topic.every_seconds, topic.next_run) if topic else ""


async def _history(session: AdminSession, from_dt: str, to_dt: str) -> dict[str, object]:
    """Both families of lane over one window, the recurring pinned above the one-shots.

    Everything is counted in Postgres — the runs and the failed tries alike — so the window may
    hold ten rows or ten thousand and the screen draws the same few hundred blocks.
    """
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
    # A recurring topic keeps its lane even when the window caught nothing: it is a permanent
    # fixture, and a lane that disappears on a quiet hour reads as the topic having been removed.
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
        # The machine face keeps the number; the page says it in words.
        "bucket_spelled": spell_duration(bucket),
        # Shares are arithmetic on the counts the lane already carries, so the lane stays a record
        # and the template asks for the bar rather than being handed a second copy of the same data.
        "tally_bar": tally_bar,
        "spell_tally": spell_tally,
        # A window with no blocks looks exactly like a broken screen, because the recurring lanes
        # are drawn whatever it holds. Both reasons are said out loud instead — and the commonest
        # is a window typed off a wall clock while the bounds are read as UTC.
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


@router.get("", responses=JSON_AND_HTML)
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
    """The async substrate, read two ways: what it still owes, and what it ran.

    Mounted at ``MountPhase.CONSOLE_SCREEN``, ahead of the console's ``/console/{app}`` catch-all:
    registered after it, this would be answered with a settings page for an app named "tasks".
    """
    if state and state not in TASK_STATES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown state")
    tasks = await list_unfinished_tasks(session, state=state, topic=topic)
    counts = await count_unfinished_tasks(session)
    context: dict[str, object] = {
        "tasks": tasks,
        # A topic per task rather than a filter in the template: the shortening is arithmetic on a
        # string, and the same rule feeds the strip's lane names and the filter's own list.
        "labels": {t.topic: topic_label(t.topic) for t in tasks},
        # In ``context``, not the page dict below: the filter swaps this fragment in on its own,
        # and a helper the full page alone carries would be missing exactly then.
        "spell_cadence": spell_cadence,
        "state_filter": state,
        "topic_filter": topic,
    }
    if not wants_json(request) and not wants_full_page(request):
        # A filter's own swap. Which panel asked is stated by the form rather than guessed from
        # which fields it carries: "back to live" sends empty bounds, and empty is also what the
        # backlog sends. Each filter replaces only its own panel — a full GET would reload the
        # page onto the server-rendered default tab, throwing the reader out of the one they were
        # reading.
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
    """The same lanes a machine can read — the strip is a picture, its data is not."""
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
